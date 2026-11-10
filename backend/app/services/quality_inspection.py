# -*- coding: utf-8 -*-
"""
会话质检服务（可复用核心模块）

设计原则：
- **可配置**：评什么维度、权重、违规项、业务人设、模型、及格线全部由 QualityInspectionConfig 决定，
  系统中只维护一份质检配置（quality_inspection_configs 表第一条/默认记录），便于统一调整标准。
- **可多处调用（被复用）**：本模块不依赖任何 router / FastAPI，只依赖模型、过滤器、LLM client。
  调用方包括：/api/qc 路由、admin 暂存区预处理、labeling 清洗、export 导出精炼等。
- **健壮**：LLM 设 timeout + 重试；LLM 不可用时返回 scored=False，绝不静默给假分；JSON 解析容错。
"""
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
import json
from datetime import datetime

from app.config import get_settings
from app.services.filter import DataFilter

settings = get_settings()


# ===================== 配置 Schema（全部可配置化） =====================

@dataclass
class DimensionConfig:
    """质检维度"""
    key: str                 # 维度标识，如 attitude / responsiveness
    name: str                # 中文名，如 服务态度
    weight: float            # 权重 0~1（多个维度之和≈1）
    description: str         # 评判要点（喂给 LLM 的 rubric）
    scale: int = 100         # 评分刻度，默认 0-100


@dataclass
class ViolationTypeConfig:
    """违规项类型"""
    key: str                 # 违规标识，如 privacy_leak
    name: str                # 中文名，如 隐私泄露
    severity: str = "medium" # high / medium / low
    description: str = ""     # 说明（喂给 LLM）


@dataclass
class QualityInspectionConfig:
    """质检完整配置（一套标准）"""
    name: str = "通用客服标准"
    description: str = "适用于一般客服会话的通用质检标准"
    business_persona: str = "你是某平台的在线客服"   # ★业务人设参数化，不写死具体品牌
    model: str = ""                                 # 空 = 跟随设置页「质检与质量评分」板块；填了则本套标准单独覆盖
    dimensions: List[DimensionConfig] = field(default_factory=list)
    violations: List[ViolationTypeConfig] = field(default_factory=list)
    pass_threshold: float = 60.0                    # 及格线
    timeout_seconds: int = 60                       # LLM 超时
    max_retries: int = 1
    language: str = "zh"


def default_qc_config() -> QualityInspectionConfig:
    """内置默认预设：实战性 / 需求把握 / 策略 / 话术自然度 / 红线检查 五维（AI 初评用）"""
    return QualityInspectionConfig(
        name="通用客服标准",
        description="客服质检通用标准：从实战性、需求把握、策略、话术自然度、红线检查五个维度逐题打分，AI 评分仅作初评。",
        business_persona="你是某平台/机构的客服或销售顾问，负责服务客户、解答咨询并推进业务。",
        model="",
        dimensions=[
            DimensionConfig(
                key="practicality", name="实战性", weight=0.20,
                description="在真实业务场景中能否有效推进、落地成交或解决问题；话术是否贴合实际、可操作，而非纸上谈兵。",
            ),
            DimensionConfig(
                key="requirement", name="需求把握", weight=0.20,
                description="是否准确识别并确认客户的真实需求与痛点；有无遗漏关键信息、误解客户意图。",
            ),
            DimensionConfig(
                key="strategy", name="策略", weight=0.20,
                description="跟进与销售策略是否得当：节奏、时机、切入点的选择是否合理，能否顺势引导。",
            ),
            DimensionConfig(
                key="naturalness", name="话术自然度", weight=0.20,
                description="表达是否自然流畅、不生硬、不说教，像真人沟通；有无套话、机械感、强推感。",
            ),
            DimensionConfig(
                key="redline", name="红线检查", weight=0.20,
                description="是否触碰合规红线：隐私泄露、违规/夸大承诺、辱骂客户、虚假宣传等。触碰红线应显著扣分。",
            ),
        ],
        violations=[
            ViolationTypeConfig("privacy_leak", "隐私泄露", "high", "向客户索要或泄露手机号、身份证、银行卡、密码、地址等隐私信息。"),
            ViolationTypeConfig("false_promise", "违规承诺", "high", "做出无法兑现或超出权限的承诺（如保证必中、保证退款无条件）。"),
            ViolationTypeConfig("exaggeration", "夸大宣传", "high", "对产品/效果作夸大、虚假宣传，误导客户预期。"),
            ViolationTypeConfig("evasion", "推诿敷衍", "medium", "把问题推给他人/其他渠道、重复套话不解决实际问题。"),
            ViolationTypeConfig("rudeness", "态度恶劣", "high", "辱骂、嘲讽、与客户发生争执或使用不礼貌用语。"),
            ViolationTypeConfig("misinformation", "信息错误", "medium", "提供了错误的业务规则、价格、流程等信息。"),
            ViolationTypeConfig("no_closure", "未闭环", "medium", "客户问题未得到最终回应或解决便结束对话。"),
        ],
        pass_threshold=60.0,
        timeout_seconds=60,
        max_retries=1,
        language="zh",
    )


# ===================== 配置序列化 =====================

def config_to_dict(cfg: QualityInspectionConfig) -> Dict[str, Any]:
    return {
        "name": cfg.name,
        "description": cfg.description,
        "business_persona": cfg.business_persona,
        "model": cfg.model,
        "dimensions": [asdict(d) for d in cfg.dimensions],
        "violations": [asdict(v) for v in cfg.violations],
        "pass_threshold": cfg.pass_threshold,
        "timeout_seconds": cfg.timeout_seconds,
        "max_retries": cfg.max_retries,
        "language": cfg.language,
    }


def config_from_dict(data: Dict[str, Any]) -> QualityInspectionConfig:
    """从 dict 反序列化；任何字段缺失/异常都回退到默认预设，保证健壮性。"""
    try:
        dims = [
            DimensionConfig(
                key=d["key"], name=d["name"],
                weight=float(d.get("weight", 0.2)),
                description=d.get("description", ""),
                scale=int(d.get("scale", 100)),
            )
            for d in data.get("dimensions", [])
        ]
        viols = [
            ViolationTypeConfig(
                key=v["key"], name=v["name"],
                severity=v.get("severity", "medium"),
                description=v.get("description", ""),
            )
            for v in data.get("violations", [])
        ]
        cfg = QualityInspectionConfig(
            name=data.get("name", "通用客服标准"),
            description=data.get("description", ""),
            business_persona=data.get("business_persona", "你是某平台的在线客服。"),
            model=data.get("model", ""),
            dimensions=dims,
            violations=viols,
            pass_threshold=float(data.get("pass_threshold", 60.0)),
            timeout_seconds=int(data.get("timeout_seconds", 60)),
            max_retries=int(data.get("max_retries", 1)),
            language=data.get("language", "zh"),
        )
        if not cfg.dimensions:
            return default_qc_config()
        return cfg
    except Exception as e:
        print(f"[WARN] 质检配置解析失败，回退默认预设: {e}")
        return default_qc_config()


# ===================== 结果对象 =====================

@dataclass
class InspectionResult:
    scored: bool                              # False=LLM 不可用/未评分
    scores: Dict[str, float] = field(default_factory=dict)   # 维度key -> 0-100
    overall_score: Optional[float] = None
    violations: List[Dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    suggestions: str = ""
    config_name: str = ""
    agent_name: Optional[str] = None
    conversation_json: Any = None
    llm_raw: str = ""
    error: str = ""
    # LLM 未返回的维度 key。_normalize_scores 会把这些维度补 0，故需单独记录，
    # 供校准分析剔除「假 0」，避免维度 MAE 被污染（主质检流程不受影响）。
    missing_dimensions: List[str] = field(default_factory=list)


# ===================== 服务主体 =====================

class QualityInspectionService:
    """
    会话质检服务（可复用核心）

    用法示例：
        svc = QualityInspectionService()                      # 用默认/DB 预设
        svc = QualityInspectionService(cfg)                  # 用指定配置
        result = svc.inspect_session(session_id, db)          # 对一个会话质检
        result = svc.inspect(conversation_text)               # 直接对文本质检
    """

    def __init__(self, config: Optional[QualityInspectionConfig] = None):
        self.config = config or default_qc_config()
        self._filter = DataFilter()
        self.client = self._build_llm_client()

    # ---------- LLM 客户端（带 timeout） ----------
    def _build_llm_client(self):
        """连接信息取设置页「质检与质量评分」板块；模型名可由本套质检标准单独覆盖"""
        try:
            from app.services.model_registry import openai_client
            client, _model = openai_client("qc", timeout=self.config.timeout_seconds)
            return client
        except Exception as e:
            print(f"[WARN] 质检 LLM client 初始化失败: {e}")
        return None

    # ---------- 组装对话文本（脱敏） ----------
    def build_conversation(
        self, session_id: str, db,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ):
        """从 raw_chats 取该会话消息，组装为 客户/客服 轮次（脱敏），并返回响应时效辅助信息。"""
        from app.models.chat import RawChat

        q = db.query(RawChat).filter(RawChat.session_id == session_id)
        if start_time is not None:
            q = q.filter(RawChat.timestamp >= start_time)
        if end_time is not None:
            q = q.filter(RawChat.timestamp <= end_time)
        messages = q.order_by(RawChat.timestamp).all()

        lines = []
        conv_json = []
        agent_name = None
        last_customer_ts = None
        gaps = []

        for m in messages:
            content = m.content or ""
            if not content.strip():
                continue
            role = "客服" if m.is_sender else "客户"
            clean = self._filter.desensitize(content)  # ★脱敏，避免 PII 外泄
            if m.is_sender and not agent_name:
                agent_name = m.sender_name or m.sender_wxid
            lines.append(f"{role}: {clean}")
            conv_json.append({
                "role": "assistant" if m.is_sender else "user",
                "speaker": role,
                "content": clean,
                "timestamp": m.timestamp,
            })
            # 计算响应时效：客户消息 -> 下一条客服消息的时间差
            if not m.is_sender:
                last_customer_ts = m.timestamp
            else:
                if last_customer_ts is not None:
                    gaps.append((m.timestamp - last_customer_ts) / 1000.0)  # 秒
                    last_customer_ts = None

        text = "\n".join(lines)
        resp_hint = ""
        if gaps:
            avg = sum(gaps) / len(gaps)
            mx = max(gaps)
            resp_hint = f"\n[系统辅助] 客户提问到客服回复的平均间隔约 {avg:.0f} 秒，最大间隔约 {mx:.0f} 秒。"
        return text, conv_json, agent_name, resp_hint

    # ---------- 主入口：对文本质检 ----------
    def inspect(self, conversation_text: str, conversation_json: Any = None) -> InspectionResult:
        if not conversation_text or not conversation_text.strip():
            return InspectionResult(scored=False, error="对话内容为空")

        conversation_text = conversation_text.strip()
        if len(conversation_text) > 8000:
            conversation_text = conversation_text[-8000:] + "\n[对话过长已截断]"

        if not self.client:
            return InspectionResult(
                scored=False,
                summary="LLM 未配置（缺少 DEEPSEEK_API_KEY / OPENAI_API_KEY），无法评分。",
                suggestions="请在配置中填入可用的 LLM API Key。",
                config_name=self.config.name,
                conversation_json=conversation_json,
                error="llm_unavailable",
            )

        prompt = self._build_prompt(conversation_text)
        raw = self._call_llm_with_retry(prompt)
        if raw is None:
            return InspectionResult(
                scored=False,
                summary="LLM 调用失败或超时，本次未评分。",
                suggestions="请稍后重试，或检查 LLM 服务可用性。",
                config_name=self.config.name,
                conversation_json=conversation_json,
                error="llm_error",
            )

        parsed = self._parse_response(raw)
        raw_scores = parsed.get("scores", {}) or {}
        scores = self._normalize_scores(raw_scores)
        overall = parsed.get("overall")
        if overall is None:
            overall = self._compute_overall(scores)
        else:
            overall = max(0.0, min(100.0, float(overall)))

        return InspectionResult(
            scored=True,
            scores=scores,
            overall_score=round(overall, 1) if overall is not None else None,
            violations=parsed.get("violations", []),
            summary=parsed.get("summary", ""),
            suggestions=parsed.get("suggestions", ""),
            config_name=self.config.name,
            conversation_json=conversation_json,
            llm_raw=raw,
            missing_dimensions=self._missing_dims(raw_scores),
        )

    # ---------- 便捷入口：直接对一个会话质检 ----------
    def inspect_session(self, session_id: str, db,
                        start_time: Optional[int] = None,
                        end_time: Optional[int] = None) -> InspectionResult:
        text, conv_json, agent_name, resp_hint = self.build_conversation(
            session_id, db, start_time, end_time
        )
        if resp_hint:
            text = text + resp_hint
        result = self.inspect(text, conv_json)
        result.agent_name = agent_name
        return result

    # ---------- Prompt 构造 ----------
    def _build_prompt(self, conversation_text: str) -> str:
        cfg = self.config
        dim_lines = "\n".join(
            f"- {d.name}（标识 {d.key}，权重 {d.weight}）：{d.description}" for d in cfg.dimensions
        )
        viol_lines = "\n".join(
            f"- {v.name}（标识 {v.key}，严重度 {v.severity}）：{v.description}" for v in cfg.violations
        )
        # 构造一个合法的示例 scores，避免给 LLM 错误 JSON 范本
        sample_scores = ", ".join(f'"{d.key}": 0' for d in cfg.dimensions)
        dim_keys = ", ".join(d.key for d in cfg.dimensions)

        return f"""你是一名客服服务质量质检专家。请根据下面的对话，对【客服】的服务质量进行评分。请逐题（即客户每次提出的需求或问题）评估客服的应对表现，再综合给出各维度分数。

## 业务背景
{cfg.business_persona}

## 评分维度（每项 0-100 分，权重已给出）
{dim_lines}

## 违规项清单（请从对话中识别，可多项；无则给空数组）
{viol_lines}

## 待质检对话
{conversation_text}

## 输出要求
只输出一个 JSON 对象（不要 markdown 代码块、不要额外说明），结构如下：
{{
  "scores": {{{sample_scores}}},
  "overall": 总分或留空(null),
  "violations": [{{"type": "违规标识", "severity": "high/medium/low", "evidence": "对话中的原文证据（简短引用）", "suggestion": "整改建议"}}],
  "summary": "总体评价（2-4 句话）",
  "suggestions": "面向客服的改进建议（2-4 条）"
}}
维度标识说明：{dim_keys}。overall 可给出整体分，留空则由系统按权重计算。

注意：
1. evidence 必须是对话里的真实原文片段，不要编造。
2. 分数要客观，依据对话实际表现，不要一律给高分。
3. 所有输出使用 {cfg.language}。
4. 本评分为 AI 初评，仅作参考，最终以人工复核为准；请客观中立，不迎合、不抬高分数。"""

    # ---------- LLM 调用（重试） ----------
    def _call_llm_with_retry(self, prompt: str) -> Optional[str]:
        from app.services.model_registry import resolve
        model = self.config.model or resolve("qc").model
        for attempt in range(self.config.max_retries + 1):
            try:
                resp = self.client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    max_tokens=1200,
                )
                return resp.choices[0].message.content.strip()
            except Exception as e:
                print(f"[ERROR] 质检 LLM 调用失败(attempt {attempt+1}): {e}")
        return None

    # ---------- 解析 ----------
    def _parse_response(self, raw: str) -> Dict[str, Any]:
        try:
            text = raw.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            # 截取第一个 { 到最后一个 }
            s, e = text.find("{"), text.rfind("}")
            if s != -1 and e != -1:
                text = text[s:e + 1]
            return json.loads(text)
        except Exception as e:
            print(f"[WARN] 质检结果解析失败: {e}")
            return {}

    def _normalize_scores(self, raw_scores: Dict[str, Any]) -> Dict[str, float]:
        out = {}
        for d in self.config.dimensions:
            try:
                v = float(raw_scores.get(d.key, 0))
            except (TypeError, ValueError):
                v = 0.0
            out[d.key] = round(max(0.0, min(100.0, v)), 1)
        return out

    def _missing_dims(self, raw_scores: Dict[str, Any]) -> List[str]:
        """LLM 未返回（或无法转为数值）的维度 key。

        _normalize_scores 会把这些维度补 0，主质检口径保持不变；这里只做「记录」，
        供校准分析把假 0 从维度偏差里剔除。
        """
        missing = []
        for d in self.config.dimensions:
            v = raw_scores.get(d.key, None)
            if v is None:
                missing.append(d.key)
                continue
            try:
                float(v)
            except (TypeError, ValueError):
                missing.append(d.key)
        return missing

    def _compute_overall(self, scores: Dict[str, float]) -> Optional[float]:
        total_w = sum(d.weight for d in self.config.dimensions)
        if total_w <= 0 or not scores:
            return None
        weighted = sum(scores.get(d.key, 0) * d.weight for d in self.config.dimensions)
        return round(weighted / total_w, 1)
