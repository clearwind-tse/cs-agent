# -*- coding: utf-8 -*-
"""
质检校准服务

- compute_metrics: 纯函数，把「AI 重跑分 vs 人工真值」的成对结果算成聚合指标
- run_calibration: 后台任务体，用某配置版本逐条重跑某分组，落 runs / run_items

设计要点：
- 校准结果只写 qc_calibration_* 表，不写 quality_inspections，避免污染主质检统计。
- 逐条重跑用「独立短会话」：查 raw_chats → 关会话 → 调 LLM → 重开写库，
  绝不在跨越多次 LLM 调用的事务里持有连接。
- metrics_json 内绝不出现 NaN/Inf（Postgres JSONB 会拒收，导致整次已付费运行丢失）。
"""
import math
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.database import get_session_local
from app.models.quality import (
    QcCalibrationItem,
    QcCalibrationRun,
    QcCalibrationRunItem,
)
from app.services.quality_inspection import (
    QualityInspectionService,
    config_from_dict,
)

# 单条偏差超过该值记为「严重偏差」
SEVERE_DELTA = 20.0


def _to_float(value: Any) -> Optional[float]:
    """转 float；不可转或非有限值一律返回 None（挡住 NaN/Inf 污染）。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _mean(values: List[float], ndigits: int = 2) -> Optional[float]:
    """安全均值：空集返回 None（绝不返回 NaN）。"""
    if not values:
        return None
    return round(sum(values) / len(values), ndigits)


def compute_metrics(
    pairs: List[Dict[str, Any]], threshold: Optional[float], dim_keys: List[str]
) -> Dict[str, Any]:
    """把逐条对比结果算成聚合指标（纯函数，无 DB 依赖，便于单测）。

    每个 pair 的字段：
        ai_scored  bool                   是否评分成功（False 一律剔除）
        ai_total   float | None           AI 总分
        ai_scores  {维度key: float}        AI 各维度分
        missing_dims [维度key]             LLM 未返回的维度（假 0，需剔除）
        ai_error   str                    未评分原因
        gold_total float | None           人工总分
        gold_scores {维度key: float}       人工各维度分
    """
    dim_keys = list(dim_keys or [])

    unscored = [p for p in pairs if not p.get("ai_scored")]
    unscored_count = len(unscored)
    empty_count = sum(1 for p in unscored if (p.get("ai_error") or "") == "empty")
    llm_error_count = sum(1 for p in unscored if (p.get("ai_error") or "") == "llm_error")
    missing_dim_count = sum(
        1 for p in pairs if p.get("missing_dims") and p.get("ai_scored")
    )

    # 参与总分比较的成对样本
    scored: List[Dict[str, Any]] = []
    deltas: List[float] = []
    for p in pairs:
        if not p.get("ai_scored"):
            continue
        ai_total = _to_float(p.get("ai_total"))
        gold_total = _to_float(p.get("gold_total"))
        if ai_total is None or gold_total is None:
            continue
        scored.append(p)
        deltas.append(ai_total - gold_total)

    abs_deltas = [abs(d) for d in deltas]
    mae_total = _mean(abs_deltas)
    bias = _mean(deltas)
    rmse = (
        round(math.sqrt(sum(d * d for d in deltas) / len(deltas)), 2)
        if deltas
        else None
    )
    severe_count = sum(1 for d in abs_deltas if d >= SEVERE_DELTA)

    # 及格一致率：仅在有总分且阈值可用时统计
    agree = 0
    compared_pass = 0
    false_pass = 0
    false_fail = 0
    if threshold is not None:
        for p in scored:
            ai_total = _to_float(p.get("ai_total"))
            gold_total = _to_float(p.get("gold_total"))
            if ai_total is None or gold_total is None:
                continue
            compared_pass += 1
            ai_pass = ai_total >= threshold
            gold_pass = gold_total >= threshold
            if ai_pass == gold_pass:
                agree += 1
            elif ai_pass and not gold_pass:
                false_pass += 1
            else:
                false_fail += 1
    pass_agree_rate = round(agree / compared_pass, 3) if compared_pass else None

    # 维度级指标：只比较 gold 与 AI 都有的维度
    mae_by_dim: Dict[str, Optional[float]] = {}
    dim_bias: Dict[str, Optional[float]] = {}
    dim_abs: Dict[str, List[float]] = {}
    dim_delta: Dict[str, List[float]] = {}
    ai_dim_values: List[float] = []
    gold_dim_values: List[float] = []
    dims_missing_in_ai: List[str] = []
    gold_dim_union: List[str] = []

    for p in scored:
        gold_scores = p.get("gold_scores") or {}
        ai_scores = p.get("ai_scores") or {}
        missing = set(p.get("missing_dims") or [])
        for k, gv in gold_scores.items():
            if k not in gold_dim_union:
                gold_dim_union.append(k)
            gf = _to_float(gv)
            if gf is None:
                continue
            # LLM 未返回该维度 → 假 0，剔除，不计入维度偏差
            if k in missing or k not in ai_scores:
                continue
            af = _to_float(ai_scores.get(k))
            if af is None:
                continue
            dim_abs.setdefault(k, []).append(abs(af - gf))
            dim_delta.setdefault(k, []).append(af - gf)
            ai_dim_values.append(af)
            gold_dim_values.append(gf)

    for k in gold_dim_union:
        mae_by_dim[k] = _mean(dim_abs.get(k, []))
        dim_bias[k] = _mean(dim_delta.get(k, []))

    # LLM 从未返回过的维度（在整个分组里都缺失）
    returned_ai_dims = set(dim_abs.keys())
    dims_missing_in_ai = [k for k in dim_keys if k not in returned_ai_dims and k in gold_dim_union]
    dims_missing_in_gold = [k for k in dim_keys if k not in gold_dim_union]

    # 维度均值（未加权 → 跨权重版本唯一可比的标量）
    ai_dim_mean = _mean(ai_dim_values)
    gold_dim_mean = _mean(gold_dim_values)
    dim_mean_bias = (
        round(ai_dim_mean - gold_dim_mean, 2)
        if ai_dim_mean is not None and gold_dim_mean is not None
        else None
    )

    return {
        "item_count": len(pairs),
        "scored_count": len(scored),
        "unscored_count": unscored_count,
        "empty_count": empty_count,
        "llm_error_count": llm_error_count,
        "missing_dim_count": missing_dim_count,
        "threshold": threshold,
        "mae_total": mae_total,
        "rmse": rmse,
        "bias": bias,
        "severe_count": severe_count,
        "severe_delta": SEVERE_DELTA,
        "pass_agree_rate": pass_agree_rate,
        "pass_compared": compared_pass,
        "false_pass": false_pass,
        "false_fail": false_fail,
        "ai_dim_mean": ai_dim_mean,
        "gold_dim_mean": gold_dim_mean,
        "dim_mean_bias": dim_mean_bias,
        "mae_by_dim": mae_by_dim,
        "dim_bias": dim_bias,
        "dim_keys": dim_keys,
        "dims_compared": sorted(returned_ai_dims),
        "dims_missing_in_ai": dims_missing_in_ai,
        "dims_missing_in_gold": dims_missing_in_gold,
        "gold_dim_keys": gold_dim_union,
        # 维度集合是否与当前版本不一致（常是「结论」，如某版本删了红线检查）
        "dim_set_changed": sorted(gold_dim_union) != sorted(dim_keys),
    }


def run_calibration(run_id: int) -> None:
    """后台任务体：用 run 快照的配置逐条重跑该分组的会话，写回 run_items 与聚合指标。"""
    SessionLocal = get_session_local()

    # ---- 阶段 1：置为 running，快照配置与待跑条目（短事务） ----
    db = SessionLocal()
    try:
        run = db.get(QcCalibrationRun, run_id)
        if not run:
            return
        cfg = config_from_dict(run.config_json or {})
        threshold = run.pass_threshold if run.pass_threshold is not None else cfg.pass_threshold
        items = [
            {
                "id": it.id,
                "session_id": it.session_id,
                "gold_total": it.gold_total,
                "gold_scores": it.gold_scores or {},
                "start_time": it.start_time,
                "end_time": it.end_time,
            }
            for it in db.query(QcCalibrationItem)
            .filter(QcCalibrationItem.group_id == run.group_id)
            .order_by(QcCalibrationItem.id.asc())
            .all()
        ]
        run.status = "running"
        run.total = len(items)
        run.done_count = 0
        run.failed_count = 0
        run.error = None
        db.commit()
    finally:
        db.close()

    dim_keys = [d.key for d in cfg.dimensions]
    svc = QualityInspectionService(cfg)  # LLM 客户端可跨条目复用
    pairs: List[Dict[str, Any]] = []
    done = 0
    failed = 0

    # ---- 阶段 2：逐条重跑（每条独立短会话，绝不长事务持连接） ----
    for it in items:
        read_db = SessionLocal()
        try:
            result = svc.inspect_session(
                it["session_id"], read_db, it["start_time"], it["end_time"]
            )
            ai_scored = bool(result.scored)
            ai_total = result.overall_score
            ai_scores = result.scores or {}
            missing = list(result.missing_dimensions or [])
            ai_error = result.error or ""
            violations = result.violations or []
            summary = result.summary or ""
        except Exception as e:  # 单条失败不影响其余
            ai_scored, ai_total, ai_scores = False, None, {}
            missing, ai_error, violations, summary = [], str(e), [], ""
            failed += 1
        finally:
            read_db.close()

        gold_total = it["gold_total"]
        gold_scores = it["gold_scores"] or {}
        delta_total = (
            round(ai_total - gold_total, 2)
            if ai_scored and ai_total is not None and gold_total is not None
            else None
        )
        per_dim_delta: Dict[str, float] = {}
        for k, gv in gold_scores.items():
            if k in missing:
                continue
            af = _to_float(ai_scores.get(k))
            gf = _to_float(gv)
            if af is None or gf is None:
                continue
            per_dim_delta[k] = round(af - gf, 2)
        pass_agree = None
        if ai_scored and ai_total is not None and gold_total is not None and threshold is not None:
            pass_agree = (ai_total >= threshold) == (gold_total >= threshold)

        write_db = SessionLocal()
        try:
            write_db.add(
                QcCalibrationRunItem(
                    run_id=run_id,
                    item_id=it["id"],
                    session_id=it["session_id"],
                    ai_total=ai_total,
                    ai_scores=ai_scores,
                    ai_scored=ai_scored,
                    ai_missing_dims=missing,
                    ai_error=(ai_error[:500] if ai_error else None),
                    gold_total=gold_total,
                    gold_scores=gold_scores,
                    delta_total=delta_total,
                    per_dim_delta=per_dim_delta,
                    pass_agree=pass_agree,
                    violations=violations,
                    summary=summary,
                )
            )
            run_row = write_db.get(QcCalibrationRun, run_id)
            if run_row:
                run_row.done_count = done + 1
                run_row.failed_count = failed
            write_db.commit()
        finally:
            write_db.close()

        pairs.append(
            {
                "ai_scored": ai_scored,
                "ai_total": ai_total,
                "ai_scores": ai_scores,
                "missing_dims": missing,
                "ai_error": ai_error,
                "gold_total": gold_total,
                "gold_scores": gold_scores,
            }
        )
        done += 1

    # ---- 阶段 3：聚合与收尾 ----
    metrics = compute_metrics(pairs, threshold, dim_keys)
    final_db = SessionLocal()
    try:
        run = final_db.get(QcCalibrationRun, run_id)
        if run:
            run.status = "done"
            run.metrics_json = metrics
            run.done_count = done
            run.failed_count = failed
            run.finished_at = datetime.utcnow()
            final_db.commit()
    finally:
        final_db.close()
