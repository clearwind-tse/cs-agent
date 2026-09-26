# -*- coding: utf-8 -*-
"""
LLM 质量评分服务
用大模型对训练数据进行质量评估和筛选
"""
import json
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from app.config import get_settings

settings = get_settings()


@dataclass
class QualityScore:
    """质量评分结果"""
    overall: float          # 总分 0-10
    completeness: float     # 完整性：对话是否完整
    relevance: float        # 相关性：是否与小蚕客服场景相关
    usefulness: float       # 实用性：是否有学习价值
    role_clarity: float     # 角色清晰度：客服/用户角色是否明确
    reason: str             # 评分理由
    suggested_category: str # 建议分类
    should_include: bool    # 是否应该纳入训练集


class LLMQualityScorer:
    """
    使用 LLM 进行质量评分
    """
    
    SCORING_PROMPT = """你是小蚕惠生活客服AI训练数据的质量评审专家。请评估以下对话是否适合用于训练客服AI。

## 对话内容：
{conversation}

## 评分维度（每项 0-10 分）：
1. **完整性**：对话是否有完整的问答结构，不是断章取义
2. **相关性**：是否与小蚕惠生活的红包、返利、霸王餐、订单、积分等业务相关
3. **实用性**：是否包含可学习的客服回答、规则说明、问题处理方法
4. **角色清晰**：客服和用户的角色是否明确可辨

## 分类选项：
- savings_explain: 省钱讲解（红包、返利、怎么点更省）
- rebate_query: 返利查询（到账、金额核对）
- coupon_issue: 优惠券问题（领券、用券、过期）
- order_problem: 订单问题（没跳转、没返利、地址错误）
- complaint: 投诉处理
- merchant: 到店霸王餐
- brand_promo: 品牌活动
- points_box: 积分盲盒
- onboarding: 新人引导
- chitchat: 闲聊（不适合训练）
- low_quality: 低质量（内容不完整、无价值）

请用 JSON 格式返回评分：
```json
{
  "completeness": 8,
  "relevance": 9,
  "usefulness": 7,
  "role_clarity": 8,
  "overall": 8,
  "category": "rebate_query",
  "reason": "这是一段完整的返利到账咨询，用户问返利为何未到账，小蚕解释了返利计算方式和到账时间，有学习价值",
  "include": true
}
```

只返回 JSON，不要其他内容。"""

    def __init__(self):
        self.client = None
        self._init_client()
    
    def _init_client(self):
        """初始化 LLM 客户端"""
        try:
            from openai import OpenAI
            if settings.deepseek_api_key:
                self.client = OpenAI(
                    api_key=settings.deepseek_api_key,
                    base_url=settings.deepseek_base_url
                )
                self.model = "deepseek-chat"
            elif settings.openai_api_key:
                self.client = OpenAI(
                    api_key=settings.openai_api_key,
                    base_url=settings.openai_base_url
                )
                self.model = "gpt-4o-mini"
        except Exception as e:
            print(f"[WARN] LLM client init failed: {e}")
    
    def score(self, conversation: str) -> Optional[QualityScore]:
        """
        对单个对话进行评分
        """
        if not self.client:
            return None
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": self.SCORING_PROMPT.format(conversation=conversation[:2000])}
                ],
                temperature=0,
                max_tokens=500
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # 提取 JSON
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0]
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0]
            
            data = json.loads(result_text)
            
            return QualityScore(
                overall=data.get("overall", 5),
                completeness=data.get("completeness", 5),
                relevance=data.get("relevance", 5),
                usefulness=data.get("usefulness", 5),
                role_clarity=data.get("role_clarity", 5),
                reason=data.get("reason", ""),
                suggested_category=data.get("category", "unknown"),
                should_include=data.get("include", False)
            )
        except Exception as e:
            print(f"[ERROR] LLM scoring failed: {e}")
            return None
    
    def batch_score(
        self, 
        conversations: List[Dict],
        min_score: float = 6.0,
        callback=None
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        批量评分并筛选
        
        Returns:
            (通过的对话列表, 未通过的对话列表)
        """
        passed = []
        rejected = []
        
        for i, conv in enumerate(conversations):
            # 构建对话文本
            if isinstance(conv, dict) and "conversations" in conv:
                text = "\n".join([
                    f"{c.get('from', c.get('role', '未知'))}: {c.get('value', c.get('content', ''))}"
                    for c in conv["conversations"]
                ])
            else:
                text = str(conv)
            
            score = self.score(text)
            
            if score:
                conv["quality_score"] = {
                    "overall": score.overall,
                    "completeness": score.completeness,
                    "relevance": score.relevance,
                    "usefulness": score.usefulness,
                    "role_clarity": score.role_clarity,
                    "reason": score.reason,
                    "llm_category": score.suggested_category
                }
                
                if score.should_include and score.overall >= min_score:
                    # 使用 LLM 建议的分类
                    if score.suggested_category not in ["casual", "low_quality"]:
                        conv["category"] = score.suggested_category
                    passed.append(conv)
                else:
                    rejected.append(conv)
            else:
                # LLM 评分失败，保留原数据
                passed.append(conv)
            
            if callback:
                callback(i + 1, len(conversations), score)
        
        return passed, rejected


class DataDeduplicator:
    """
    数据去重
    移除重复或过于相似的对话
    """
    
    def __init__(self, similarity_threshold: float = 0.85):
        self.threshold = similarity_threshold
        self.embeddings_cache = {}
    
    def _get_embedding(self, text: str) -> List[float]:
        """获取文本 embedding"""
        from app.services.embedding import get_embedding_service
        service = get_embedding_service()
        return service.embed_text(text)
    
    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """计算余弦相似度"""
        import math
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0
        return dot / (norm_a * norm_b)
    
    def deduplicate(self, conversations: List[Dict]) -> List[Dict]:
        """
        去重
        保留每组相似对话中质量最高的一个
        """
        if not conversations:
            return []
        
        unique = []
        unique_embeddings = []
        
        for conv in conversations:
            # 获取对话文本
            if "text" in conv:
                text = conv["text"]
            elif "conversations" in conv:
                text = " ".join([
                    c.get("value", c.get("content", ""))
                    for c in conv["conversations"]
                ])
            else:
                unique.append(conv)
                continue
            
            # 计算 embedding
            try:
                emb = self._get_embedding(text[:500])  # 限制长度
            except:
                unique.append(conv)
                continue
            
            # 检查是否与已有的重复
            is_duplicate = False
            for existing_emb in unique_embeddings:
                sim = self._cosine_similarity(emb, existing_emb)
                if sim >= self.threshold:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                unique.append(conv)
                unique_embeddings.append(emb)
        
        return unique


class ConversationRewriter:
    """
    对话改写/增强
    用 LLM 改善对话质量或生成变体
    """
    
    REWRITE_PROMPT = """请改写以下小蚕客服对话，使其更加专业、完整、有学习价值。

原始对话：
{conversation}

改写要求：
1. 保持原意，但让表达更专业清晰
2. 如果对话不完整，补充合理的结尾
3. 明确客服和用户的角色
4. 突出小蚕客服的规则说明与问题处理亮点

请用以下格式返回：
用户: xxx
小蚕: xxx
用户: xxx
小蚕: xxx
"""

    def __init__(self):
        self.client = None
        self._init_client()
    
    def _init_client(self):
        try:
            from openai import OpenAI
            if settings.deepseek_api_key:
                self.client = OpenAI(
                    api_key=settings.deepseek_api_key,
                    base_url=settings.deepseek_base_url
                )
                self.model = "deepseek-chat"
            elif settings.openai_api_key:
                self.client = OpenAI(
                    api_key=settings.openai_api_key,
                    base_url=settings.openai_base_url
                )
                self.model = "gpt-4o-mini"
        except:
            pass
    
    def rewrite(self, conversation: str) -> Optional[str]:
        """改写单个对话"""
        if not self.client:
            return None
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": self.REWRITE_PROMPT.format(conversation=conversation)}
                ],
                temperature=0.7,
                max_tokens=1000
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[ERROR] Rewrite failed: {e}")
            return None


class RoleLabeler:
    """
    角色标注
    自动识别对话中的客服和用户角色
    """
    
    LABEL_PROMPT = """分析以下对话，判断每句话是小蚕客服说的还是用户说的。

对话：
{conversation}

小蚕客服的特征：解释红包/返利规则、说明活动、处理订单问题、引导操作
用户的特征：提问、反馈问题、表达不满、咨询怎么用

请返回 JSON 数组，每个元素包含 role（"sales" 或 "customer"）和 content：
```json
[
  {"role": "customer", "content": "返利怎么还没到账？"},
  {"role": "sales", "content": "返利是按实付金额算的，订单完成后24小时内到账"}
]
```"""

    def __init__(self):
        self.client = None
        self._init_client()
    
    def _init_client(self):
        try:
            from openai import OpenAI
            if settings.deepseek_api_key:
                self.client = OpenAI(
                    api_key=settings.deepseek_api_key,
                    base_url=settings.deepseek_base_url
                )
                self.model = "deepseek-chat"
            elif settings.openai_api_key:
                self.client = OpenAI(
                    api_key=settings.openai_api_key,
                    base_url=settings.openai_base_url
                )
                self.model = "gpt-4o-mini"
        except:
            pass
    
    def label(self, conversation: str) -> Optional[List[Dict]]:
        """标注角色"""
        if not self.client:
            return None
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": self.LABEL_PROMPT.format(conversation=conversation)}
                ],
                temperature=0,
                max_tokens=1000
            )
            
            result = response.choices[0].message.content.strip()
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0]
            
            return json.loads(result)
        except Exception as e:
            print(f"[ERROR] Role labeling failed: {e}")
            return None
