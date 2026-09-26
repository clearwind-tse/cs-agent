# -*- coding: utf-8 -*-
"""
大模型训练数据生成服务
将微信聊天记录转换为高质量的训练数据
"""
import re
import json
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime
import hashlib

from pydantic import BaseModel


# ==================== 数据模型 ====================

class DataQuality(str, Enum):
    """数据质量等级"""
    HIGH = "high"           # 高质量：完整问答、技术讨论
    MEDIUM = "medium"       # 中等：有价值但不完整
    LOW = "low"             # 低质量：闲聊、碎片
    REJECTED = "rejected"   # 拒绝：敏感、无意义


class ContentCategory(str, Enum):
    """内容分类 - 小蚕惠生活客服场景"""
    SAVINGS_EXPLAIN = "savings_explain"   # 玩法说明 / 怎么领券
    REBATE_QUERY = "rebate_query"         # 返利查询 / 提现
    COUPON_ISSUE = "coupon_issue"         # 红包 / 券问题
    ORDER_PROBLEM = "order_problem"       # 订单异常
    COMPLAINT = "complaint"               # 投诉 / 差评
    MERCHANT = "merchant"                 # 到店霸王餐 / 门店
    BRAND_PROMO = "brand_promo"           # 大牌特惠
    POINTS_BOX = "points_box"             # 积分 / 盲盒
    ONBOARDING = "onboarding"             # 新人引导
    CHITCHAT = "chitchat"                 # 闲聊
    KNOWLEDGE = "knowledge"               # 知识分享
    NOTIFICATION = "notification"         # 通知


@dataclass
class ConversationTurn:
    """对话轮次"""
    role: str           # user / assistant / system
    content: str
    sender: str = ""    # 原始发送者
    timestamp: int = 0


@dataclass
class TrainingExample:
    """训练样本"""
    id: str
    conversations: List[ConversationTurn]
    category: ContentCategory = ContentCategory.CHITCHAT
    quality: DataQuality = DataQuality.MEDIUM
    source_session: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


# ==================== 清洗规则 ====================

class DataCleaningRules:
    """数据清洗规则配置"""
    
    # 完全过滤的内容模式
    REJECT_PATTERNS = [
        r'^\[.*\]$',                    # 纯表情 [微笑]
        r'^<?xml.*',                    # XML 消息
        r'^https?://\S+$',              # 纯链接
        r'^\d+$',                       # 纯数字
        r'^[哈呵嘿]{2,}$',              # 哈哈哈
        r'^[嗯恩唔]{1,3}$',             # 嗯嗯
        r'^(好的?|OK|ok|收到|谢谢|感谢|不客气|没事)$',  # 简单回复
        r'^(在吗|在不|忙吗|方便吗)\??$',  # 无意义开场
        r'^\?+$',                       # 纯问号
        r'^\.+$',                       # 纯句号
    ]
    
    # 敏感信息模式 (需要脱敏)
    SENSITIVE_PATTERNS = [
        (r'\b1[3-9]\d{9}\b', '[手机号]'),                    # 手机号
        (r'\b\d{15,18}[xX]?\b', '[身份证]'),                 # 身份证
        (r'\b\d{16,19}\b', '[银行卡]'),                      # 银行卡
        (r'(密码|口令|password)[:：\s]*\S+', r'\1:[已脱敏]'),  # 密码
        (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[邮箱]'),  # 邮箱
        (r'(验证码|验证|code)[:：\s]*\d{4,6}', r'\1:[已脱敏]'),  # 验证码
    ]
    
    # 高价值内容关键词 - 小蚕惠生活客服场景
    HIGH_VALUE_KEYWORDS = [
        # 优惠 / 红包
        '红包', '优惠券', '优惠', '券', '神券', '力度', '门槛', '返利', '返现',
        '省钱', '薅羊毛', '回血', '霸王餐', '白嫖', '大牌', '特惠', '折扣',
        # 外卖 / 渠道
        '外卖', '美团', '饿了么', '京东', '淘宝', '闪购', '到店', '下单', '订单',
        # 返利 / 提现
        '提现', '余额', '到账', '结算', '手续费',
        # 积分 / 盲盒
        '积分', '盲盒', '五折', '抽奖', '兑换',
        # 问题场景
        '用不了', '过期', '没到账', '没返', '取消', '退款', '投诉', '换了',
        # 品牌
        '茶百道', '沪上阿姨', '霸王茶姬', '奈雪', '茶颜悦色', '夸父',
        # 问答类
        '怎么', '如何', '为什么', '什么是', '能不能', '可以吗', '请问',
        '多少', '几天', '多久', '包含', '有没有',
    ]
    
    # 最小内容长度
    MIN_CONTENT_LENGTH = 5
    MIN_CONVERSATION_TURNS = 2
    MAX_SINGLE_MESSAGE_LENGTH = 2000


class DataCleaner:
    """数据清洗器"""
    
    def __init__(self, rules: DataCleaningRules = None):
        self.rules = rules or DataCleaningRules()
        self._compiled_reject = [re.compile(p, re.IGNORECASE) for p in self.rules.REJECT_PATTERNS]
        self._compiled_sensitive = [(re.compile(p[0], re.IGNORECASE), p[1]) for p in self.rules.SENSITIVE_PATTERNS]
    
    def should_reject(self, content: str) -> bool:
        """判断是否应该拒绝该内容"""
        if not content or len(content.strip()) < self.rules.MIN_CONTENT_LENGTH:
            return True
        
        content = content.strip()
        for pattern in self._compiled_reject:
            if pattern.match(content):
                return True
        
        return False
    
    def desensitize(self, content: str) -> str:
        """脱敏处理"""
        for pattern, replacement in self._compiled_sensitive:
            content = pattern.sub(replacement, content)
        return content
    
    def clean(self, content: str) -> Optional[str]:
        """清洗单条内容，返回 None 表示应该丢弃"""
        if self.should_reject(content):
            return None
        
        # 脱敏
        content = self.desensitize(content)
        
        # 截断过长内容
        if len(content) > self.rules.MAX_SINGLE_MESSAGE_LENGTH:
            content = content[:self.rules.MAX_SINGLE_MESSAGE_LENGTH] + "..."
        
        return content.strip()
    
    def has_high_value_keywords(self, content: str) -> bool:
        """检查是否包含高价值关键词"""
        content_lower = content.lower()
        return any(kw.lower() in content_lower for kw in self.rules.HIGH_VALUE_KEYWORDS)


# ==================== 对话重构 ====================

class ConversationBuilder:
    """对话重构器 - 将碎片消息组装成完整对话"""
    
    def __init__(
        self,
        time_window_seconds: int = 300,  # 5分钟内的消息视为同一对话
        max_turns_per_conversation: int = 20,
        my_identifiers: List[str] = None  # "我"的标识列表
    ):
        self.time_window = time_window_seconds
        self.max_turns = max_turns_per_conversation
        self.my_ids = set(my_identifiers or ["我"])
    
    def is_me(self, sender: str) -> bool:
        """判断是否是"我"发送的"""
        return sender in self.my_ids or sender == "我"
    
    def build_conversations(
        self, 
        messages: List[Dict[str, Any]]
    ) -> List[List[Dict[str, Any]]]:
        """
        将消息列表切分为多个对话
        
        Args:
            messages: 按时间排序的消息列表，每条包含 sender, content, timestamp
        
        Returns:
            对话列表，每个对话是消息列表
        """
        if not messages:
            return []
        
        conversations = []
        current_conv = []
        last_time = messages[0].get('timestamp', 0)
        
        for msg in messages:
            msg_time = msg.get('timestamp', 0)
            
            # 时间窗口切分
            if msg_time - last_time > self.time_window and current_conv:
                conversations.append(current_conv)
                current_conv = []
            
            # 轮次数量限制
            if len(current_conv) >= self.max_turns:
                conversations.append(current_conv)
                current_conv = []
            
            current_conv.append(msg)
            last_time = msg_time
        
        if current_conv:
            conversations.append(current_conv)
        
        return conversations
    
    def to_turns(
        self, 
        messages: List[Dict[str, Any]], 
        merge_consecutive: bool = True
    ) -> List[ConversationTurn]:
        """
        将消息转换为标准对话轮次
        
        Args:
            messages: 消息列表
            merge_consecutive: 是否合并同一人连续发送的消息
        
        Returns:
            对话轮次列表
        """
        if not messages:
            return []
        
        turns = []
        current_role = None
        current_content = []
        current_sender = ""
        
        for msg in messages:
            sender = msg.get('sender_name') or msg.get('sender', '未知')
            content = msg.get('content', '')
            is_sender = msg.get('is_sender', False)
            
            # 确定角色
            role = "assistant" if (self.is_me(sender) or is_sender) else "user"
            
            if merge_consecutive and role == current_role:
                # 合并同角色连续消息
                current_content.append(content)
            else:
                # 保存之前的轮次
                if current_content:
                    turns.append(ConversationTurn(
                        role=current_role,
                        content="\n".join(current_content),
                        sender=current_sender
                    ))
                
                current_role = role
                current_content = [content]
                current_sender = sender
        
        # 保存最后一个轮次
        if current_content:
            turns.append(ConversationTurn(
                role=current_role,
                content="\n".join(current_content),
                sender=current_sender
            ))
        
        return turns


# ==================== 质量评估 ====================

class QualityEvaluator:
    """数据质量评估器"""
    
    def __init__(self, cleaner: DataCleaner = None):
        self.cleaner = cleaner or DataCleaner()
    
    def evaluate(self, turns: List[ConversationTurn]) -> Tuple[DataQuality, float]:
        """
        评估对话质量
        
        Returns:
            (质量等级, 分数 0-1)
        """
        if len(turns) < 2:
            return DataQuality.REJECTED, 0.0
        
        score = 0.0
        factors = []
        
        # 因素1: 对话轮次数 (0-0.2)
        turn_score = min(len(turns) / 10, 1.0) * 0.2
        factors.append(('turns', turn_score))
        score += turn_score
        
        # 因素2: 平均内容长度 (0-0.2)
        avg_length = sum(len(t.content) for t in turns) / len(turns)
        length_score = min(avg_length / 100, 1.0) * 0.2
        factors.append(('length', length_score))
        score += length_score
        
        # 因素3: 是否包含问答结构 (0-0.3)
        has_question = any('?' in t.content or '？' in t.content for t in turns if t.role == 'user')
        has_answer = any(len(t.content) > 20 for t in turns if t.role == 'assistant')
        qa_score = 0.3 if (has_question and has_answer) else 0.1
        factors.append(('qa_structure', qa_score))
        score += qa_score
        
        # 因素4: 高价值关键词 (0-0.3)
        all_content = " ".join(t.content for t in turns)
        keyword_count = sum(1 for kw in DataCleaningRules.HIGH_VALUE_KEYWORDS if kw.lower() in all_content.lower())
        keyword_score = min(keyword_count / 5, 1.0) * 0.3
        factors.append(('keywords', keyword_score))
        score += keyword_score
        
        # 确定质量等级
        if score >= 0.7:
            quality = DataQuality.HIGH
        elif score >= 0.4:
            quality = DataQuality.MEDIUM
        elif score >= 0.2:
            quality = DataQuality.LOW
        else:
            quality = DataQuality.REJECTED
        
        return quality, score
    
    def categorize(self, turns: List[ConversationTurn]) -> ContentCategory:
        """内容分类 - 小蚕惠生活客服场景"""
        all_content = " ".join(t.content for t in turns).lower()

        # 投诉（最高优先级）
        complaint_keywords = ['投诉', '差评', '骗人', '坑', '态度', '换了', '太差', '举报']
        if any(kw in all_content for kw in complaint_keywords):
            return ContentCategory.COMPLAINT

        # 订单异常
        order_keywords = ['没返上', '没返', '取消', '漏了', '没到账', '异常', '补录']
        if any(kw in all_content for kw in order_keywords):
            return ContentCategory.ORDER_PROBLEM

        # 返利 / 提现
        rebate_keywords = ['返利', '提现', '余额', '到账', '结算', '手续费']
        if any(kw in all_content for kw in rebate_keywords):
            return ContentCategory.REBATE_QUERY

        # 红包 / 券问题
        coupon_keywords = ['红包', '券', '用不了', '过期', '门槛', '抵扣']
        if any(kw in all_content for kw in coupon_keywords):
            return ContentCategory.COUPON_ISSUE

        # 到店霸王餐 / 门店
        merchant_keywords = ['霸王餐', '到店', '门店', '核销', '入驻', '中签']
        if any(kw in all_content for kw in merchant_keywords):
            return ContentCategory.MERCHANT

        # 积分 / 盲盒
        points_keywords = ['积分', '盲盒', '五折', '抽奖', '兑换']
        if any(kw in all_content for kw in points_keywords):
            return ContentCategory.POINTS_BOX

        # 大牌特惠
        brand_keywords = ['茶百道', '沪上阿姨', '霸王茶姬', '奈雪', '茶颜悦色', '夸父', '大牌', '特惠']
        if any(kw in all_content for kw in brand_keywords):
            return ContentCategory.BRAND_PROMO

        # 新人引导
        onboarding_keywords = ['新人', '注册', '下载', '第一次', '邀请码', '绑定手机']
        if any(kw in all_content for kw in onboarding_keywords):
            return ContentCategory.ONBOARDING

        # 玩法说明
        savings_keywords = ['怎么用', '怎么领', '领券', '省钱', '薅羊毛', '优惠', '返现', '力度']
        if any(kw in all_content for kw in savings_keywords):
            return ContentCategory.SAVINGS_EXPLAIN

        # 问答类
        if any(c in all_content for c in ['怎么', '如何', '什么', '为什么', '?', '？']):
            return ContentCategory.SAVINGS_EXPLAIN

        return ContentCategory.CHITCHAT


# ==================== 格式导出 ====================

class TrainingDataExporter:
    """训练数据导出器"""
    
    # 隐私脱敏模式（业务价：红包力度 20-18、返利 15 元等一律保留）
    PRIVACY_PATTERNS = [
        (r'(1[3-9]\d)\d{4}(\d{4})', r'\1****\2'),                          # 手机号 138****1234
        (r'(\d{3})\d{11}(\d{4})', r'\1***********\2'),                     # 身份证
        (r'\b(?:XCH|DD|MT|WM)[-_]?\d{6,}\b', '[订单号]'),                    # 平台订单号
        (r'(\d{4})\d{8,12}(\d{4})', r'\1****\2'),                          # 银行卡 / 收款账号
        (r'([a-zA-Z0-9])[a-zA-Z0-9._%+-]*(@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', r'\1***\2'),  # 邮箱
    ]

    @staticmethod
    def _desensitize_content(text: str) -> str:
        """
        脱敏处理隐私信息

        脱敏：手机号 / 身份证 / 订单号 / 银行卡或收款账号 / 邮箱
        保留：业务价格信息（红包力度 20-18、返利 15 元等一律原样保留）
        """
        import re
        result = text

        # 1. 隐私信息脱敏
        for pattern, repl in TrainingDataExporter.PRIVACY_PATTERNS:
            result = re.sub(pattern, repl, result)

        # 2. 明文密码 / 验证码
        result = re.sub(r'((?:密码|口令|password)[:：\s]*)\S+', r'\1[已脱敏]', result, flags=re.IGNORECASE)
        result = re.sub(r'((?:验证码|验证|code)[:：\s]*)\d{4,6}', r'\1[已脱敏]', result, flags=re.IGNORECASE)

        # 3. URL 直接移除
        result = re.sub(r'https?://[^\s\u4e00-\u9fa5]+', '', result)
        result = re.sub(r'(?<![:\w])//[a-zA-Z0-9\-]+\.[a-zA-Z0-9\-./\w]+', '', result)

        # 4. 清理多余空格和空行
        result = re.sub(r'  +', ' ', result)
        result = re.sub(r'\n\s*\n\s*\n', '\n\n', result)

        return result

    @staticmethod
    def _should_skip_conversation(turns: list, min_turns: int = 4) -> bool:
        """检查对话是否应该被跳过（过短）"""
        return len(turns) < min_turns
    
    @staticmethod
    def _truncate_conversation(turns: list, max_turns: int = 40) -> list:
        """截断过长对话"""
        if len(turns) <= max_turns:
            return turns
        return turns[:max_turns]
    
    @staticmethod
    def to_sharegpt(examples: List[TrainingExample], include_system: bool = True) -> List[Dict]:
        """
        导出为 ShareGPT 格式
        适用于：LLaMA-Factory, FastChat 等
        """
        dataset = []
        
        # 根据分类选择不同的 system prompt
        # 按分类选择 system prompt（小蚕惠生活·客服人设）
        SYSTEM_PROMPTS = {
            ContentCategory.SAVINGS_EXPLAIN: "我是小蚕惠生活（小蚕霸王餐）的客服小蚕。用户想了解怎么点外卖更省钱、返利怎么算，我用大白话讲清楚：先领红包再下单、返利每单最低15元、到店霸王餐写好评可0元吃。说话专业又亲和，可称「您」，可用标点，价格力度直接说，不绕弯子。",
            ContentCategory.REBATE_QUERY: "我是小蚕客服小蚕，负责帮用户查返利。用户问返利到哪了、为啥少了，我先安抚再给准话：正常返利在订单完成后24小时内到账，金额按实付比例计算。说话专业亲和、直接爽快，可称「您」。",
            ContentCategory.COUPON_ISSUE: "我是小蚕客服小蚕，管外卖红包和优惠券。用户遇到券领不到、用不了、过期的问题，我一步步教他领券入口、使用门槛和有效期规则。说话耐心，可称「您」，涉及红包力度（如20-18）直接报数。",
            ContentCategory.ORDER_PROBLEM: "我是小蚕客服小蚕，处理订单异常：没跳转、没返利、券没用上、地址写错等。我先问清订单号和时间，再判断原因并给解决方案。说话专业、负责，可称「您」，需要隐私信息时提示用户注意保护。",
            ContentCategory.COMPLAINT: "我是小蚕客服小蚕，面对用户投诉和不满。先共情道歉、承认问题，再给出明确的补偿或处理方案，绝不推诿。语气真诚、有担当，可称「您」，不跟用户争对错。",
            ContentCategory.MERCHANT: "我是小蚕客服小蚕，负责到店霸王餐、商家合作与探店体验。用户咨询参与门店、中签规则、到店流程、内容要求，我说清规则：中签后按时到店、拍图写真实体验、审核通过即返现。说话专业亲和，可称「您」。",
            ContentCategory.BRAND_PROMO: "我是小蚕客服小蚕，介绍平台大牌特惠与合作品牌（茶百道、沪上阿姨、霸王茶姬、奈雪、茶颜悦色、夸父炸串等）。用户问有哪些品牌、活动力度，我直接讲清优惠和参与方式，语气热情但不浮夸，可称「您」。",
            ContentCategory.POINTS_BOX: "我是小蚕客服小蚕，负责积分和盲盒玩法。用户问积分怎么攒、盲盒怎么开、抽到券怎么用，我讲清规则：做任务攒积分、积分兑券、五折盲盒开品牌代金券。说话清楚有条理，可称「您」。",
            ContentCategory.ONBOARDING: "我是小蚕客服小蚕，带新用户第一次上手。用户问怎么用、怎么开始省钱，我按步骤讲：下载App、注册登录、领红包、下单返利、提现。语气友好亲切，鼓励用户动手试，可称「您」。",
            ContentCategory.CHITCHAT: "我是小蚕客服小蚕，负责日常闲聊和礼貌性对话。用户打招呼、道谢、说客套话时，我简短热情地回应，并顺势引导到省钱话题。语气自然亲切，可称「您」。",
            ContentCategory.KNOWLEDGE: "我是小蚕客服小蚕，分享本地生活省钱知识：外卖红包怎么叠、返利平台怎么选、到店探店技巧、薅羊毛避坑。内容实用、口语化，可称「您」。",
            ContentCategory.NOTIFICATION: "我是小蚕客服小蚕，发送平台通知：红包到账、活动开始、中签提醒、提现进度。语言简洁明确，突出关键信息和时间，可称「您」。",
        }
        DEFAULT_PROMPT = "我是小蚕惠生活（小蚕霸王餐）的客服小蚕，帮用户点外卖省钱、参加到店霸王餐、领红包拿返利。说话专业亲和、简洁直接，可称「您」，涉及红包力度和返利金额直接说明。"

        for ex in examples:
            conversations = []
            
            if include_system:
                system_prompt = SYSTEM_PROMPTS.get(ex.category, DEFAULT_PROMPT)
                conversations.append({
                    "from": "system",
                    "value": system_prompt
                })
            
            for turn in ex.conversations:
                content = TrainingDataExporter._desensitize_content(turn.content)
                conversations.append({
                    "from": "gpt" if turn.role == "assistant" else "human",
                    "value": content
                })
            
            if len(conversations) > (1 if include_system else 0):
                dataset.append({
                    "id": ex.id,
                    "conversations": conversations,
                    "category": ex.category.value,
                    "quality": ex.quality.value
                })
        
        return dataset
    
    @staticmethod
    def to_alpaca(examples: List[TrainingExample]) -> List[Dict]:
        """
        导出为 Alpaca 格式
        适用于：Stanford Alpaca, text-generation-webui 等
        """
        dataset = []
        
        for ex in examples:
            turns = ex.conversations
            
            # 寻找问答对
            for i in range(len(turns) - 1):
                if turns[i].role == "user" and turns[i + 1].role == "assistant":
                    # 收集上下文
                    context = ""
                    if i > 0:
                        context = "\n".join(t.content for t in turns[:i])
                    
                    dataset.append({
                        "instruction": TrainingDataExporter._desensitize_content(turns[i].content),
                        "input": TrainingDataExporter._desensitize_content(context[:500]) if context else "",
                        "output": TrainingDataExporter._desensitize_content(turns[i + 1].content),
                        "category": ex.category.value
                    })
        
        return dataset
    
    @staticmethod
    def to_openai_chat(examples: List[TrainingExample]) -> List[Dict]:
        """
        导出为 OpenAI Chat 格式
        适用于：OpenAI Fine-tuning
        """
        dataset = []
        
        for ex in examples:
            messages = [
                {"role": "system", "content": "你是小蚕惠生活（小蚕霸王餐）的客服小蚕，帮用户点外卖省钱、领红包、拿返利、参加到店霸王餐。说话专业亲和、简洁直接，可称「您」，价格力度和返利金额可如实告知。"}
            ]
            
            for turn in ex.conversations:
                content = TrainingDataExporter._desensitize_content(turn.content)
                messages.append({
                    "role": turn.role if turn.role in ["user", "assistant"] else "user",
                    "content": content
                })
            
            dataset.append({"messages": messages})
        
        return dataset
    
    @staticmethod
    def to_jsonl(examples: List[TrainingExample]) -> List[Dict]:
        """
        导出为 JSONL 格式
        通用格式，保留完整信息
        """
        dataset = []
        
        for ex in examples:
            # 构建对话文本
            conversation_text = []
            for turn in ex.conversations:
                role_label = "用户" if turn.role == "user" else "助手"
                content = TrainingDataExporter._desensitize_content(turn.content)
                conversation_text.append(f"{role_label}: {content}")
            
            dataset.append({
                "id": ex.id,
                "text": "\n".join(conversation_text),
                "conversations": [
                    {"role": t.role, "content": TrainingDataExporter._desensitize_content(t.content)}
                    for t in ex.conversations
                ],
                "category": ex.category.value,
                "quality": ex.quality.value,
                "session_id": ex.source_session,
                "metadata": ex.metadata
            })
        
        return dataset
    
    @staticmethod
    def to_dpo_pairs(examples: List[TrainingExample]) -> List[Dict]:
        """
        导出为 DPO 偏好对格式
        需要有 chosen/rejected 对
        注意：这需要人工标注或 LLM 打分来生成偏好对
        """
        # TODO: 实现 DPO 格式导出
        # 需要额外的偏好标注数据
        return []
    
    @staticmethod
    def to_rag(examples: List[TrainingExample]) -> List[Dict]:
        """
        导出为 RAG 知识库格式
        每条数据为 question + answer 的问答对
        适用于：火山引擎等知识库平台
        """
        dataset = []
        
        for ex in examples:
            turns = ex.conversations
            
            # 提取所有 user 和 assistant 消息
            user_contents = [t.content for t in turns if t.role == "user"]
            assist_contents = [t.content for t in turns if t.role == "assistant"]
            
            if not user_contents or not assist_contents:
                continue
            
            # 将第一个 user 消息作为 question，所有 assistant 回复合并为 answer
            question = TrainingDataExporter._desensitize_content(user_contents[0])
            answer = "\n".join(
                TrainingDataExporter._desensitize_content(c) for c in assist_contents
            )
            
            dataset.append({
                "question": question,
                "answer": answer,
                "category": ex.category.value
            })
        
        return dataset


# ==================== 主处理流程 ====================

class TrainingDataPipeline:
    """训练数据生成主流程"""
    
    def __init__(
        self,
        cleaner: DataCleaner = None,
        builder: ConversationBuilder = None,
        evaluator: QualityEvaluator = None,
        min_quality: DataQuality = DataQuality.MEDIUM,
        merge_consecutive: bool = False  # 默认为 False
    ):
        self.cleaner = cleaner or DataCleaner()
        self.builder = builder or ConversationBuilder()
        self.evaluator = evaluator or QualityEvaluator(self.cleaner)
        self.min_quality = min_quality
        self.merge_consecutive = merge_consecutive
    
    def process_session(
        self, 
        session_id: str,
        messages: List[Dict[str, Any]]
    ) -> List[TrainingExample]:
        """
        处理单个会话的消息
        
        Args:
            session_id: 会话ID
            messages: 原始消息列表
        
        Returns:
            训练样本列表
        """
        examples = []
        
        # Step 1: 清洗
        cleaned_messages = []
        for msg in messages:
            content = msg.get('content', '')
            cleaned_content = self.cleaner.clean(content)
            if cleaned_content:
                cleaned_msg = msg.copy()
                cleaned_msg['content'] = cleaned_content
                cleaned_messages.append(cleaned_msg)
        
        if not cleaned_messages:
            return []
        
        # Step 2: 切分对话
        conversations = self.builder.build_conversations(cleaned_messages)
        
        # Step 3: 转换 & 评估
        for i, conv in enumerate(conversations):
            turns = self.builder.to_turns(conv, merge_consecutive=self.merge_consecutive)
            
            if len(turns) < 2:
                continue
            
            quality, score = self.evaluator.evaluate(turns)
            
            # 质量过滤
            quality_order = [DataQuality.REJECTED, DataQuality.LOW, DataQuality.MEDIUM, DataQuality.HIGH]
            if quality_order.index(quality) < quality_order.index(self.min_quality):
                continue
            
            category = self.evaluator.categorize(turns)
            
            # 生成唯一ID
            example_id = hashlib.md5(f"{session_id}_{i}_{turns[0].content[:20]}".encode()).hexdigest()[:12]
            
            examples.append(TrainingExample(
                id=example_id,
                conversations=turns,
                category=category,
                quality=quality,
                source_session=session_id,
                metadata={
                    "score": score,
                    "turn_count": len(turns),
                    "total_length": sum(len(t.content) for t in turns)
                }
            ))
        
        return examples
    
    def export(
        self,
        examples: List[TrainingExample],
        format: str = "sharegpt"
    ) -> List[Dict]:
        """导出为指定格式"""
        if format == "sharegpt":
            return TrainingDataExporter.to_sharegpt(examples)
        elif format == "alpaca":
            return TrainingDataExporter.to_alpaca(examples)
        elif format == "openai":
            return TrainingDataExporter.to_openai_chat(examples)
        elif format == "jsonl":
            return TrainingDataExporter.to_jsonl(examples)
        elif format == "rag":
            return TrainingDataExporter.to_rag(examples)
        elif format == "dpo":
            return TrainingDataExporter.to_dpo_pairs(examples)
        else:
            raise ValueError(f"Unknown format: {format}")
    
    def get_statistics(self, examples: List[TrainingExample]) -> Dict[str, Any]:
        """生成数据集统计信息"""
        if not examples:
            return {"total": 0}
        
        stats = {
            "total": len(examples),
            "by_quality": {},
            "by_category": {},
            "avg_turns": 0,
            "avg_length": 0
        }
        
        total_turns = 0
        total_length = 0
        
        for ex in examples:
            # 质量分布
            q = ex.quality.value
            stats["by_quality"][q] = stats["by_quality"].get(q, 0) + 1
            
            # 类别分布
            c = ex.category.value
            stats["by_category"][c] = stats["by_category"].get(c, 0) + 1
            
            # 长度统计
            total_turns += len(ex.conversations)
            total_length += sum(len(t.content) for t in ex.conversations)
        
        stats["avg_turns"] = round(total_turns / len(examples), 2)
        stats["avg_length"] = round(total_length / len(examples), 2)
        
        return stats
