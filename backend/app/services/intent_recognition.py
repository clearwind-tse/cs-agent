# -*- coding: utf-8 -*-
"""
意图识别服务

职责：
1. 分析用户消息，识别意图类别
2. 提取情绪信号
3. 输出结构化路由决策
4. 支持词典初筛 + LLM精判的两级架构
"""
from typing import Dict, List, Optional
import re

from app.services.agent_registry import AgentContext, AgentRegistry, get_agent_registry


class IntentResult:
    """意图识别结果"""
    def __init__(self,
                 intent: str,
                 confidence: float,
                 sub_intent: Optional[str] = None,
                 frustration_signals: List[str] = None,
                 emotion_type: Optional[str] = None,
                 emotion_intensity: int = 1):
        self.intent = intent
        self.confidence = confidence
        self.sub_intent = sub_intent
        self.frustration_signals = frustration_signals or []
        self.emotion_type = emotion_type
        self.emotion_intensity = emotion_intensity

    def to_dict(self) -> Dict:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "sub_intent": self.sub_intent,
            "frustration_signals": self.frustration_signals,
            "emotion_type": self.emotion_type,
            "emotion_intensity": self.emotion_intensity,
        }


class IntentRecognitionService:
    """意图识别服务"""

    # 意图类别定义
    INTENT_CATEGORIES = {
        "order_status": {
            "name": "订单状态查询",
            "keywords": ["订单", "查订单", "订单号", "我的订单", "订单在哪", "订单状态"],
            "sub_intents": ["查询进度", "修改订单", "取消订单"]
        },
        "logistics": {
            "name": "物流追踪",
            "keywords": ["物流", "快递", "包裹", "发货", "到哪了", "配送", "运输", "快递单号"],
            "sub_intents": ["查询物流", "催促发货", "修改地址", "拒收退回"]
        },
        "refund_return": {
            "name": "退货退款",
            "keywords": ["退款", "退货", "换货", "退钱", "不合格", "质量问题", "不满意", "不想买了"],
            "sub_intents": ["申请退款", "查询退款进度", "换货", "退货地址"]
        },
        "product_inquiry": {
            "name": "产品咨询",
            "keywords": ["是什么", "怎么用", "参数", "规格", "哪里有", "多少钱", "优惠", "促销"],
            "sub_intents": ["功能咨询", "价格咨询", "库存查询", "使用方法"]
        },
        "complaint": {
            "name": "投诉建议",
            "keywords": ["投诉", "差评", "12315", "经理", "骗子", "垃圾", "失望", "太恶心了"],
            "sub_intents": ["服务投诉", "产品质量", "物流投诉", "退款纠纷"]
        },
        "general_faq": {
            "name": "通用咨询",
            "keywords": ["怎么", "如何", "为什么", "哪里", "什么时候", "客服"],
            "sub_intents": ["客服时间", "支付方式", "配送范围", "售后服务"]
        }
    }

    # 情绪关键词
    EMOTION_KEYWORDS = {
        "anger": ["愤怒", "气死", "暴怒", "恼火", "烦死", "讨厌", "恶心", "无语", "垃圾", "骗子", "sb", "傻逼", "滚"],
        "anxiety": ["着急", "担心", "害怕", "紧张", "什么时候", "等多久", "还没", "一直没"],
        "disappointment": ["失望", "沮丧", "心灰意冷", "后悔", "白买了", "太失望了"],
        "confusion": ["困惑", "不明白", "不懂", "怎么回事", "什么意思", "什么鬼"],
        "satisfaction": ["满意", "感谢", "谢谢", "好的", "棒", "不错", "解决", "满意"],
        "gratitude": ["感激", "感动", "辛苦了", "感谢感谢", "太感谢了"]
    }

    # 命令式 / 催促表达：字面无情绪词，但客户明显不耐烦（教材 Ch6「中文情绪表达的隐晦性」）
    IMPERATIVE_SIGNALS = ["给我", "快点", "赶紧", "马上", "立刻", "现在就", "别废话", "退我", "赔我"]

    # 关键词权重：泛词（"订单"）会被大量场景命中，必须降权；
    # 强特征词（"退款""退货"）承载主要意图语义，加权。
    KEYWORD_WEIGHTS = {
        "订单": 0.35, "订单号": 0.35, "我的订单": 0.5, "订单状态": 1.0, "查订单": 1.0,
        "订单在哪": 1.0, "物流": 1.0, "快递": 0.8, "包裹": 0.8, "发货": 0.8,
        "到哪了": 0.8, "配送": 0.6, "运输": 0.6, "快递单号": 1.0,
        "退款": 1.3, "退货": 1.3, "换货": 1.1, "退钱": 1.2, "质量问题": 1.0,
        "怎么": 0.3, "如何": 0.3, "为什么": 0.4, "哪里": 0.3, "客服": 0.4,
    }

    # 挫败信号（正则模式）
    FRUSTRATION_PATTERNS = [
        r"连续.{0,4}次",
        r"又是.{0,4}次",
        r"每次.{0,6}都",
        r"到底.{0,6}才",
        r"！{2,}",
        r"？{2,}",
    ]

    def __init__(self, registry: Optional[AgentRegistry] = None):
        self.registry = registry or get_agent_registry()

    def detect_intent(self, message: str, user_id: Optional[str] = None) -> IntentResult:
        """
        识别用户消息的意图

        流程（教材 Ch3：词典初筛 + LLM 精判两级架构）：
        1. 词典初筛（毫秒级，带权重）
        2. 情绪信号检测
        3. LLM 精判（词表无命中 / 命中但区分度不足时）
        """
        # 步骤1：词典初筛
        keyword_hits = self._keyword_scan(message)

        # 步骤2：情绪信号检测
        emotion_result = self._detect_emotion(message)

        # 步骤3：是否需要 LLM 精判
        #
        # 之前的缺陷：只要恰好命中 1 个意图就直接返回，不再看 LLM。
        # 结果 "是的,订单发错货" 里只有泛词"订单"，被直接判成 order_status（0.77），
        # 路由到订单查询 Agent，于是又追问了一遍订单号。
        # 现在只有「强特征词命中 且 明显领先第二名」才直接采信。
        if keyword_hits:
            ranked = sorted(keyword_hits.items(), key=lambda kv: kv[1], reverse=True)
            best_intent, best_score = ranked[0]
            second_score = ranked[1][1] if len(ranked) > 1 else 0.0

            strong_enough = best_score >= 1.0
            clearly_ahead = (best_score - second_score) >= 0.4
            if strong_enough and clearly_ahead:
                return self._post_correct(IntentResult(
                    intent=best_intent,
                    confidence=min(0.6 + 0.2 * best_score, 0.95),
                    emotion_type=emotion_result.get("type"),
                    emotion_intensity=emotion_result.get("intensity", 1),
                    frustration_signals=emotion_result.get("signals", []),
                ), emotion_result)
            # 区分度不足 → 交给 LLM，并用词典排序结果作为先验提示
            result = self._llm_classify(message, emotion_result, hint=best_intent)
            return self._post_correct(result, emotion_result)

        return self._post_correct(self._llm_classify(message, emotion_result), emotion_result)

    def _post_correct(self, result: IntentResult, emotion_result: Dict) -> IntentResult:
        """
        分类后校正：LLM 把「纯辱骂」判成 general_faq 是常见错误。

        客户骂人但没说诉求时，本质上就是投诉——按 complaint 处理才能进入
        共情+定位的流程，而不是回一句"请问有什么可以帮您"。
        """
        if (result.emotion_intensity >= 3
                and result.intent in ("general_faq", "product_inquiry")
                and emotion_result.get("type") == "anger"):
            result.intent = "complaint"
            result.confidence = max(result.confidence, 0.7)
            result.sub_intent = result.sub_intent or "情绪宣泄"
        return result

    def _keyword_scan(self, message: str) -> Dict[str, float]:
        """关键词加权扫描，返回 {intent: 加权得分}"""
        scores = {}
        msg_lower = message.lower()

        for intent, config in self.INTENT_CATEGORIES.items():
            score = 0.0
            for kw in config["keywords"]:
                if kw in msg_lower:
                    score += self.KEYWORD_WEIGHTS.get(kw, 0.8)

            if score > 0:
                scores[intent] = round(score, 2)

        return scores

    def _detect_emotion(self, message: str) -> Dict:
        """检测情绪（教材 Ch6：宁多检不漏检，负面情绪优先级高于正面词）"""
        result = {"type": "neutral", "intensity": 1, "signals": []}
        msg_lower = message.lower()

        # 检测挫败信号
        for pattern in self.FRUSTRATION_PATTERNS:
            matches = re.findall(pattern, message)
            if matches:
                result["signals"].extend(matches)

        # 检测情绪关键词
        for emotion, keywords in self.EMOTION_KEYWORDS.items():
            for kw in keywords:
                if kw in msg_lower:
                    if result["type"] in ("neutral", "satisfaction", "gratitude") or emotion == "anger":
                        result["type"] = emotion
                    result["intensity"] = max(result["intensity"], 2)
                    result["signals"].append(kw)

        # 命令式 / 催促表达：字面无情绪词，但客户已经不耐烦
        imperatives = [w for w in self.IMPERATIVE_SIGNALS if w in msg_lower]
        if imperatives:
            result["signals"].extend(imperatives)
            if result["type"] in ("neutral", "satisfaction", "gratitude"):
                result["type"] = "anxiety"
            result["intensity"] = max(result["intensity"], 2)

        # 特殊情绪信号提升
        strong_signals = ["投诉", "12315", "差评", "骗子", "垃圾", "sb"]
        if any(sig in msg_lower for sig in strong_signals):
            result["type"] = "anger"
            result["intensity"] = max(result["intensity"], 4)

        # 感叹号/问号堆叠 → 情绪加重
        if re.search(r"[!！]{2,}|[?？]{2,}", message):
            result["intensity"] = min(5, result["intensity"] + 1)

        return result

    def _llm_classify(self, message: str, emotion_result: Dict,
                      hint: Optional[str] = None) -> IntentResult:
        """LLM精判（hint 为词典初筛的先验，帮助模型消歧）"""
        from app.services.quiz import _get_llm_client
        client, model = _get_llm_client("chat")
        if client is None:
            return IntentResult(
                intent=hint or "general_faq", confidence=0.5,
                emotion_type=emotion_result.get("type"),
                emotion_intensity=emotion_result.get("intensity", 1),
                frustration_signals=emotion_result.get("signals", []),
            )

        prompt = f"""你是一个专业的客服意图分类器。请分析以下客户消息，输出JSON格式的分类结果。

## 意图类别（6类）
- order_status: 查询订单状态、订单信息
- logistics: 查询物流进度、发货状态、包裹位置
- refund_return: 申请退款、退货、换货、要求退还某笔订单的款项/权益
- product_inquiry: 咨询产品功能、规格、价格
- complaint: 投诉、辱骂、抱怨服务、威胁差评/12315
- general_faq: 其他通用咨询

## 判定要点
- 客户说「给我退X」「退我钱」「把钱退了」这类祈使句，即使没说「退款」二字，也算 refund_return。
- 只是催促/骂人但没有具体诉求，算 complaint。
- 关键词初筛提示：{hint or "无"}

## 情绪强度（1-5级）
- {emotion_result.get('intensity', 1)}

## 客户消息
{message}

## 输出格式（严格JSON）
{{
  "intent": "意图类别",
  "sub_intent": "具体子意图或null",
  "confidence": 0.0-1.0,
  "reasoning": "分类依据（一句话）"
}}"""

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=200
            )

            content = response.choices[0].message.content
            import json
            m = re.search(r"\{.*\}", content or "", re.S)
            result = json.loads(m.group(0) if m else content)

            intent = result.get("intent", "general_faq")
            if intent not in self.INTENT_CATEGORIES:
                intent = hint or "general_faq"

            return IntentResult(
                intent=intent,
                confidence=result.get("confidence", 0.7),
                sub_intent=result.get("sub_intent"),
                emotion_type=emotion_result.get("type"),
                emotion_intensity=emotion_result.get("intensity", 1),
                frustration_signals=emotion_result.get("signals", [])
            )
        except Exception as e:
            print(f"[IntentRecognition] LLM分类失败: {e}")
            return IntentResult(
                intent=hint or "general_faq",
                confidence=0.5,
                emotion_type=emotion_result.get("type"),
                emotion_intensity=emotion_result.get("intensity", 1)
            )

    def build_context(self, message: str, user_id: Optional[str] = None) -> AgentContext:
        """构建Agent执行上下文"""
        intent_result = self.detect_intent(message, user_id)

        return AgentContext(
            session_id=f"user_{user_id}" if user_id else "anonymous",
            user_id=user_id,
            message=message,
            intent=intent_result.intent,
            intent_confidence=intent_result.confidence,
            sub_intent=intent_result.sub_intent,
            emotion_type=intent_result.emotion_type,
            emotion_intensity=intent_result.emotion_intensity,
            frustration_signals=intent_result.frustration_signals,
            turn_count=0,
            dialog_phase="intake"
        )
