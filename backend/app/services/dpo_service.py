# -*- coding: utf-8 -*-
"""
DPO 偏好对服务

负责生成、标注、管理 DPO 训练所需的偏好对数据
"""
import json
import hashlib
from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from app.models.database import get_session_local
from app.models.chat import RawChat, LabeledConversation
from app.models.dpo import (
    DpoPreferencePair, 
    SftTrainingSample,
    PreferenceType,
    AnnotationStatus
)
from app.services.training_data import ContentCategory
from app.services.sft_service import sft_service


class DpoDataService:
    """DPO 偏好对数据服务"""
    
    # 拒绝模式（算错运费、态度生硬等）
    REJECTION_PATTERNS = [
        r'运费.*不对',
        r'算.*错',
        r'态度.*生硬',
        r'语气.*差',
        r'不.*专业',
        r'错误.*答案',
        r'不符合.*规定',
    ]
    
    def __init__(self):
        pass
    
    def generate_preference_pairs(
        self,
        min_quality: str = "medium",
        max_pairs: int = 500,
        rejected_per_pair: int = 3
    ) -> List[DpoPreferencePair]:
        """
        从 SFT 样本生成 DPO 偏好对

        策略：
        1. 按业务分类聚合多条回复
        2. 为每个业务问题生成 1 条 chosen + N 条类型不同的 rejected
           （N = rejected_per_pair，默认 3：计算错误 / 态度生硬 / 违规承诺）
        3. 标注系统自动标记明显错误的回复作为 rejected

        Returns:
            DPO 偏好对列表
        """
        # 获取高质量 SFT 样本
        samples_result = sft_service.get_samples(
            is_approved=True,
            limit=max_pairs * 3,  # 获取足够多的样本
            offset=0
        )
        
        samples = samples_result.get("samples", [])
        pairs = []
        
        # 按类别分组
        by_category: Dict[str, List[Dict]] = {}
        for s in samples:
            cat = s.get("category", "unknown")
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(s)
        
        # 为每个类别生成偏好对
        for category, category_samples in by_category.items():
            if len(category_samples) < 2:
                continue
            
            # 采样多个问题
            sampled = category_samples[:max_pairs // len(by_category)]
            
            for sample in sampled:
                pair = self._create_preference_pair(
                    sample, category, num_rejected=rejected_per_pair
                )
                if pair:
                    pairs.append(pair)
                    
                    if len(pairs) >= max_pairs:
                        break
            
            if len(pairs) >= max_pairs:
                break
        
        return pairs
    
    def _create_preference_pair(
        self,
        sample: Dict,
        category: str,
        num_rejected: int = 3
    ) -> Optional[DpoPreferencePair]:
        """
        创建单个偏好对（1 chosen × N rejected）

        模拟逻辑：
        - chosen: 原 SFT 样本的回复（假设是好的）
        - rejected: 构造 N 条错误类型各不相同的回复
          （计算错误 / 态度生硬 / 违规承诺）
        """
        prompt = sample.get("instruction", "")
        chosen_reply = sample.get("output", "")

        # 生成 N 条不同类型的 rejected 回复
        bad_replies = self._generate_bad_replies(prompt, category, num_rejected)

        # 构建候选回复列表：index 0 = chosen，其余为 rejected
        candidate_replies = [
            {
                "index": 0,
                "reply": chosen_reply,
                "source": "sft_model",
                "error_type": None,
            }
        ]
        rejected_indices = []
        for i, bad in enumerate(bad_replies, start=1):
            candidate_replies.append({
                "index": i,
                "reply": bad["reply"],
                "source": "baseline_model",
                "error_type": bad["error_type"],
                "preference_type": bad["preference_type"],
            })
            rejected_indices.append(i)

        # 生成唯一 ID（纳入来源样本 id，避免同一业务问题重复生成时碰撞）
        pair_id = hashlib.md5(
            f"{sample.get('id', '')}_{prompt[:50]}_{chosen_reply[:30]}".encode()
        ).hexdigest()[:16]

        # 单一错误类型时直接用它，多样时标记 mixed
        pref_types = {b["preference_type"] for b in bad_replies}
        preference_type = pref_types.pop() if len(pref_types) == 1 else "mixed"

        return DpoPreferencePair(
            id=pair_id,
            prompt=prompt,
            business_category=category,
            candidate_replies=candidate_replies,
            chosen_index=0,  # 默认选中 SFT 模型的回复
            rejected_indices=rejected_indices,
            preference_type=preference_type,
            annotation_status=AnnotationStatus.PENDING.value,
            quality_score=sample.get("quality_score", 7.0),
            difficulty_level="medium",
            source_session_id=sample.get("source_session_id", "")
        )
    
    # 错误类型 → 中文标签
    ERROR_TYPE_LABELS = {
        "accuracy": "计算错误",
        "tone": "态度生硬",
        "compliance": "违规承诺",
    }

    # 各业务分类下，按错误类型分组的「坏回复」样例池
    BAD_REPLY_POOLS = {
        "complaint": {
            "accuracy": [
                "您这笔退款算下来是 12 块，没算错。",
                "多扣的 3 块钱返利是正常的，不用退。",
            ],
            "tone": [
                "这不是我们的问题，是您自己的原因。",
                "您这种情况我们不管，找别人去吧。",
            ],
            "compliance": [
                "您先把差评删了，我就帮您处理。",
                "给您退 50 块，但您得在群里帮我们宣传一下。",
            ],
        },
        "order_problem": {
            "accuracy": [
                "运费就是这么多，没有错。",
                "这单返利应该是 8 块，不会少您的。",
            ],
            "tone": [
                "订单问题您自己看去，我没空解释。",
                "这个没法退，您自己看着办。",
            ],
            "compliance": [
                "您先把评价改成五星，我这边才能帮您催单。",
                "私下拉个群发个红包给您，就不用走平台了。",
            ],
        },
        "rebate_query": {
            "accuracy": [
                "返利应该是 15 元，没算错。",
                "您这单按 3% 算就是 2 块 4，没问题。",
            ],
            "tone": [
                "什么时候到账我不清楚，您自己看。",
                "返利规则就那样，看不懂我也没办法。",
            ],
            "compliance": [
                "您多下几单凑够金额，我私下给您返现。",
                "帮我们拉 5 个新用户，返利翻倍。",
            ],
        },
        "coupon_issue": {
            "accuracy": [
                "这个券就是减 3 块，您说的 5 块是记错了。",
                "门槛是满 30 减 5，您这单 28 用不了。",
            ],
            "tone": [
                "券过期了就用不了，没办法。",
                "您领券的时候没看清楚规则吗？",
            ],
            "compliance": [
                "您先用我的码领券，返利我私下转您。",
                "把券分享到群里，我给您发红包。",
            ],
        },
        "merchant": {
            "accuracy": [
                "霸王餐返现是 20，不会多给。",
                "到店消费满 100 才返，您这单不够。",
            ],
            "tone": [
                "您不想写就算了，没人逼您。",
                "霸王餐名额就这些，抢不到怪不了别人。",
            ],
            "compliance": [
                "霸王餐就是要写好评，不然不返现。",
                "必须给五星好评加晒图，否则不给返。",
            ],
        },
        "brand_promo": {
            "accuracy": [
                "这个活动就是打 7 折，没有更低的。",
                "满减是满 50 减 8，您理解错了。",
            ],
            "tone": [
                "活动规则都写着，自己不会看吗？",
                "特惠就这一档，爱买不买。",
            ],
            "compliance": [
                "您帮我转发朋友圈，我私下给您返 10 块。",
                "拉 3 个好友下单，我给您额外红包。",
            ],
        },
        "points_box": {
            "accuracy": [
                "积分是 1 元 10 分，您算错了。",
                "盲盒开出的是 50 分，不会更多。",
            ],
            "tone": [
                "积分规则就是这样，不满意也没办法。",
                "盲盒开什么看运气，怪不了平台。",
            ],
            "compliance": [
                "多拉几个人助力，我给您刷积分。",
                "私下帮您刷单攒积分，别声张。",
            ],
        },
        "onboarding": {
            "accuracy": [
                "新用户红包就是 5 块，不是 20。",
                "首单立减 3 块，您记错了。",
            ],
            "tone": [
                "注册流程就那样，自己搞不定吗？",
                "不会用就问问身边人。",
            ],
            "compliance": [
                "您用我的邀请码注册，我私下返您 5 块。",
                "多注册几个号，每个都能领红包。",
            ],
        },
        "savings_explain": {
            "accuracy": [
                "每月最多省 200，不是 500。",
                "叠加优惠不能同时用，您算多了。",
            ],
            "tone": [
                "省钱方法就这些，学不会也没办法。",
                "这么简单都不会，仔细看看。",
            ],
            "compliance": [
                "您把账号借我用用，帮您刷更高返利。",
                "走线下交易，能多给您返点。",
            ],
        },
    }

    # 通用兜底池（分类未覆盖时使用）
    GENERIC_BAD_POOL = {
        "accuracy": ["金额就是这样，没算错。"],
        "tone": ["这个问题我不清楚，您自己看吧。"],
        "compliance": ["您配合一下，我私下给您补偿。"],
    }

    def _generate_bad_replies(
        self,
        prompt: str,
        category: str,
        count: int = 3
    ) -> List[Dict[str, str]]:
        """
        生成 N 条错误类型各不相同的 rejected 回复

        覆盖的错误类型（按优先级）：
        - accuracy   : 算错金额 / 运费 / 返利
        - tone       : 态度生硬 / 推诿 / 指责用户
        - compliance : 违规承诺 / 诱导好评 / 私下交易

        Returns:
            [{"reply": ..., "error_type": "计算错误", "preference_type": "accuracy"}, ...]
        """
        pool = self.BAD_REPLY_POOLS.get(category) or self.GENERIC_BAD_POOL
        order = ["accuracy", "tone", "compliance"]

        hash_hex = hashlib.md5(prompt.encode()).hexdigest()
        results: List[Dict[str, str]] = []

        for j in range(min(count, len(order))):
            etype = order[j]
            replies = pool.get(etype) or self.GENERIC_BAD_POOL.get(etype) or ["抱歉，这个问题我处理不了。"]
            # 用 prompt 哈希的不同片段做轮转，保证不同业务问题挑到不同措辞
            slot = hash_hex[(j * 4) % max(len(hash_hex) - 8, 1):][:8] or hash_hex[:8]
            idx = int(slot, 16) % len(replies)
            results.append({
                "reply": replies[idx],
                "error_type": self.ERROR_TYPE_LABELS[etype],
                "preference_type": etype,
            })

        return results
    
    def save_pairs(self, pairs: List[DpoPreferencePair]) -> int:
        """保存偏好对到数据库（幂等：已存在则更新，不存在则插入）"""
        SessionLocal = get_session_local()
        db = SessionLocal()

        try:
            count = 0
            for pair in pairs:
                # merge: 按主键存在性自动 INSERT 或 UPDATE，避免重复生成时
                # 因确定性哈希 ID 命中唯一约束而报错
                db.merge(pair)
                count += 1

            db.commit()
            return count
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    
    def get_pairs(
        self,
        category: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """查询偏好对列表"""
        SessionLocal = get_session_local()
        db = SessionLocal()
        
        try:
            query = db.query(DpoPreferencePair).filter(
                DpoPreferencePair.is_active == True
            )
            
            if category:
                query = query.filter(DpoPreferencePair.business_category == category)
            
            if status:
                query = query.filter(DpoPreferencePair.annotation_status == status)
            
            total = query.count()
            pairs = query.order_by(
                DpoPreferencePair.created_at.desc()
            ).limit(limit).offset(offset).all()
            
            return {
                "total": total,
                "pairs": [
                    {
                        "id": p.id,
                        "prompt": p.prompt,
                        "business_category": p.business_category,
                        "candidate_count": len(p.candidate_replies),
                        "annotation_status": p.annotation_status,
                        "annotated_by": p.annotated_by,
                        "quality_score": p.quality_score,
                        "created_at": p.created_at.isoformat() if p.created_at else None
                    }
                    for p in pairs
                ]
            }
        finally:
            db.close()
    
    def get_pair_detail(self, pair_id: str) -> Optional[Dict]:
        """获取偏好对详情"""
        SessionLocal = get_session_local()
        db = SessionLocal()
        
        try:
            pair = db.query(DpoPreferencePair).filter(
                DpoPreferencePair.id == pair_id
            ).first()
            
            if not pair:
                return None
            
            # 获取 chosen 和 rejected 回复
            candidates = pair.candidate_replies or []
            chosen_reply = None
            rejected_replies = []
            rejected_details = []

            for c in candidates:
                idx = c.get("index")
                if idx == pair.chosen_index:
                    chosen_reply = c.get("reply", "")
                elif idx in (pair.rejected_indices or []):
                    rejected_replies.append(c.get("reply", ""))
                    rejected_details.append({
                        "index": idx,
                        "reply": c.get("reply", ""),
                        "error_type": c.get("error_type") or "",
                        "preference_type": c.get("preference_type") or "",
                    })

            return {
                "id": pair.id,
                "prompt": pair.prompt,
                "business_category": pair.business_category,
                "scenario_description": pair.scenario_description,
                "chosen_reply": chosen_reply,
                "rejected_replies": rejected_replies,
                "rejected_details": rejected_details,
                "preference_type": pair.preference_type,
                "annotation_status": pair.annotation_status,
                "annotated_by": pair.annotated_by,
                "annotated_at": pair.annotated_at.isoformat() if pair.annotated_at else None,
                "annotation_notes": pair.annotation_notes,
                "quality_score": pair.quality_score,
                "difficulty_level": pair.difficulty_level,
                "created_at": pair.created_at.isoformat() if pair.created_at else None
            }
        finally:
            db.close()
    
    def annotate_pair(
        self,
        pair_id: str,
        chosen_index: int,
        annotated_by: str,
        notes: Optional[str] = None
    ) -> bool:
        """
        标注偏好对
        
        Args:
            pair_id: 偏好对ID
            chosen_index: 选中的回复索引
            annotated_by: 标注人
            notes: 标注备注
        
        Returns:
            是否成功
        """
        SessionLocal = get_session_local()
        db = SessionLocal()
        
        try:
            pair = db.query(DpoPreferencePair).filter(
                DpoPreferencePair.id == pair_id
            ).first()
            
            if not pair:
                return False
            
            # 更新标注信息
            pair.chosen_index = chosen_index
            pair.rejected_indices = [
                i for i in range(len(pair.candidate_replies or []))
                if i != chosen_index
            ]
            pair.annotation_status = AnnotationStatus.ANNOTATED.value
            pair.annotated_by = annotated_by
            pair.annotated_at = datetime.utcnow()
            pair.annotation_notes = notes
            
            db.commit()
            return True
        finally:
            db.close()
    
    def export_for_training(
        self,
        format: str = "dpo",
        include_unannotated: bool = True
    ) -> List[Dict]:
        """
        导出 DPO 训练数据

        格式：
        ```json
        [
          {
            "prompt": "用户问题",
            "chosen": "选中的回复",
            "rejected": "被拒绝的回复",
            "annotation_status": "annotated / pending"
          }
        ]
        ```

        Args:
            format: 导出格式（目前仅 dpo）
            include_unannotated: 是否包含尚未人工标注的偏好对。默认 True，
                让业务主管标注前也能先用自动生成的 chosen/rejected 做首轮 DPO；
                已标注记录会在 annotation_status 字段中标记为 annotated。
        """
        SessionLocal = get_session_local()
        db = SessionLocal()

        try:
            query = db.query(DpoPreferencePair).filter(
                DpoPreferencePair.is_active == True
            )
            if not include_unannotated:
                query = query.filter(
                    DpoPreferencePair.annotation_status == AnnotationStatus.ANNOTATED.value
                )
            pairs = query.all()

            dataset = []
            for pair in pairs:
                candidates = pair.candidate_replies or []

                # 找到 chosen 和全部 rejected
                chosen_reply = None
                rejected_items = []

                for c in candidates:
                    idx = c.get("index")
                    if idx == pair.chosen_index:
                        chosen_reply = c.get("reply", "")
                    elif idx in (pair.rejected_indices or []):
                        rejected_items.append({
                            "reply": c.get("reply", ""),
                            "error_type": c.get("error_type") or "",
                            "preference_type": c.get("preference_type") or "",
                            "index": idx,
                        })

                if not chosen_reply or not rejected_items:
                    continue

                # 1 chosen × K rejected → 展开成 K 条独立 DPO 样本
                # （兼容 TRL / LLaMA-Factory 的标准 {prompt, chosen, rejected} 格式）
                for item in rejected_items:
                    dataset.append({
                        "prompt": pair.prompt,
                        "chosen": chosen_reply,
                        "rejected": item["reply"],
                        "error_type": item["error_type"],
                        "business_category": pair.business_category,
                        "preference_type": item["preference_type"] or pair.preference_type,
                        "annotation_status": pair.annotation_status,
                    })

            return dataset

        finally:
            db.close()
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取 DPO 数据统计"""
        SessionLocal = get_session_local()
        db = SessionLocal()
        
        try:
            total = db.query(DpoPreferencePair).count()
            pending = db.query(DpoPreferencePair).filter(
                DpoPreferencePair.annotation_status == AnnotationStatus.PENDING.value
            ).count()
            annotated = db.query(DpoPreferencePair).filter(
                DpoPreferencePair.annotation_status == AnnotationStatus.ANNOTATED.value
            ).count()
            
            # 按类别统计
            by_category = db.query(
                DpoPreferencePair.business_category,
                func.count(DpoPreferencePair.id)
            ).group_by(DpoPreferencePair.business_category).all()
            
            return {
                "total": total,
                "pending": pending,
                "annotated": annotated,
                "by_category": dict(by_category)
            }
        finally:
            db.close()


# 全局实例
dpo_service = DpoDataService()
