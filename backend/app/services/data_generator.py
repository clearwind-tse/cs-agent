# -*- coding: utf-8 -*-
"""
LLM 驱动的训练数据批量生成服务

业务场景：小蚕惠生活（小蚕霸王餐）——帮你点外卖省钱、吃喝玩乐的本地生活平台。
生成立场：平台客服视角（客服自称「小蚕 / 蚕宝」，专业亲和）。
严格复刻真实微信客服对话风格。
"""
import json
import re
import random
import time
import threading
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from app.config import get_settings

settings = get_settings()


# ==================== 场景模板定义 ====================

SCENARIO_TEMPLATES = [
    # ===== savings_explain (4 场景)：玩法说明 / 怎么领券 =====
    {
        "category": "savings_explain",
        "title": "新人问怎么用",
        "user_persona": "刚听说小蚕 想知道怎么点外卖省钱",
        "user_opening": "小蚕惠生活怎么用啊\n听说点外卖能便宜不少",
        "key_topics": ["先领券再下单", "返利最低15元起", "每月省500-1000"],
    },
    {
        "category": "savings_explain",
        "title": "问红包力度",
        "user_opening": "你们红包一般能减多少啊",
        "user_persona": "对价格敏感 想确认优惠力度",
        "key_topics": ["20-18", "15-13", "比直接下单便宜"],
    },
    {
        "category": "savings_explain",
        "title": "问支持哪些平台",
        "user_opening": "小蚕支持美团饿了么吗",
        "user_persona": "点外卖渠道多 想确认覆盖范围",
        "key_topics": ["美团", "饿了么", "京东外卖", "淘宝闪购"],
    },
    {
        "category": "savings_explain",
        "title": "问返利怎么算",
        "user_opening": "返利是怎么算的啊\n是每单都有吗",
        "user_persona": "想知道返利规则",
        "key_topics": ["按实付金额", "部分订单", "最低15元起"],
    },

    # ===== rebate_query (4 场景)：返利到账 / 提现 =====
    {
        "category": "rebate_query",
        "title": "返利没到账",
        "user_opening": "我上周点的外卖 返利怎么还没到",
        "user_persona": "下单后等返利 有点着急",
        "key_topics": ["要订单号", "1-3个工作日", "帮查余额"],
    },
    {
        "category": "rebate_query",
        "title": "怎么提现",
        "user_opening": "返利余额怎么提出来啊",
        "user_persona": "想把手里的返利提现",
        "key_topics": ["满1元可提", "微信支付宝", "秒到账"],
    },
    {
        "category": "rebate_query",
        "title": "返利金额不对",
        "user_opening": "我返利金额好像少了\n是不是算错了",
        "user_persona": "发现返利和预期不符",
        "key_topics": ["要截图核对", "按实付算", "渠道比例不同"],
    },
    {
        "category": "rebate_query",
        "title": "提现审核太久",
        "user_opening": "提现怎么这么久还在审核",
        "user_persona": "提现超时 有点担心",
        "key_topics": ["正常秒到", "可能触发风控", "加急核实"],
    },

    # ===== coupon_issue (3 场景)：红包 / 券问题 =====
    {
        "category": "coupon_issue",
        "title": "券用不了",
        "user_opening": "我领的红包怎么用不了\n下单没减钱",
        "user_persona": "领了券但下单没抵扣",
        "key_topics": ["没到门槛", "有效期", "渠道要对"],
    },
    {
        "category": "coupon_issue",
        "title": "券过期了",
        "user_opening": "我的券怎么过期了 也没提醒",
        "user_persona": "券过期想补",
        "key_topics": ["券面有有效期", "过期无法补", "每天能领新券"],
    },
    {
        "category": "coupon_issue",
        "title": "券在哪领",
        "user_opening": "红包在哪里领啊 找不到入口",
        "user_persona": "新用户找不到领券入口",
        "key_topics": ["App首页", "午餐晚餐下午茶", "每天可领"],
    },

    # ===== order_problem (3 场景)：订单异常 =====
    {
        "category": "order_problem",
        "title": "这单没返上",
        "user_opening": "我这单好像没返上\n是不是漏了",
        "user_persona": "下单后没拿到返利",
        "key_topics": ["要订单号", "是否从小蚕跳转", "没跳无法补录"],
    },
    {
        "category": "order_problem",
        "title": "订单取消",
        "user_opening": "订单取消的话 返利还算吗",
        "user_persona": "取消订单 关心返利",
        "key_topics": ["取消退款会扣回", "建议确认收货"],
    },
    {
        "category": "order_problem",
        "title": "没从小蚕跳转",
        "user_opening": "我直接在美团下的单\n能补返利吗",
        "user_persona": "忘了从小蚕跳转下单",
        "key_topics": ["无法补录", "下次先领券", "说明跳转方式"],
    },

    # ===== complaint (3 场景)：投诉 / 差评 =====
    {
        "category": "complaint",
        "title": "霸王餐被换套餐",
        "user_opening": "我要投诉\n霸王餐到店给我换了别的套餐",
        "user_persona": "到店体验和活动不符 情绪不满",
        "key_topics": ["致歉", "要门店和时间", "登记反馈1-2天"],
    },
    {
        "category": "complaint",
        "title": "质疑平台",
        "user_opening": "你们提现审核这么久 是不是骗人的",
        "user_persona": "对平台有戒心",
        "key_topics": ["安抚", "看提现记录", "加急核实"],
    },
    {
        "category": "complaint",
        "title": "券没提醒就过期",
        "user_opening": "券过期一点提醒都没有\n太坑了",
        "user_persona": "因券过期不满",
        "key_topics": ["致歉", "说明券面有效期", "补偿建议"],
    },

    # ===== merchant (3 场景)：到店霸王餐 / 商家 =====
    {
        "category": "merchant",
        "title": "霸王餐怎么参加",
        "user_opening": "到店霸王餐怎么参加啊\n要发什么",
        "user_persona": "想参加到店霸王餐",
        "key_topics": ["App报名", "中签后到店", "发真实感受"],
    },
    {
        "category": "merchant",
        "title": "中签怎么用",
        "user_opening": "我中签了 到店怎么核销啊",
        "user_persona": "中签后不知道怎么用",
        "key_topics": ["按活动页要求", "到店核销", "发感受"],
    },
    {
        "category": "merchant",
        "title": "商家想入驻",
        "user_opening": "我们店想入驻小蚕\n怎么联系",
        "user_persona": "商家想谈合作",
        "key_topics": ["要门店城市联系方式", "对接商务", "欢迎入驻"],
    },

    # ===== brand_promo (3 场景)：大牌特惠 =====
    {
        "category": "brand_promo",
        "title": "问茶百道",
        "user_opening": "茶百道在小蚕有优惠吗",
        "user_persona": "想喝奶茶找券",
        "key_topics": ["已入驻", "App搜品牌", "全天有优惠"],
    },
    {
        "category": "brand_promo",
        "title": "问奈雪",
        "user_opening": "奈雪的茶能便宜多少啊",
        "user_persona": "想点奈雪 关心优惠",
        "key_topics": ["券面写优惠", "搜品牌名", "比门店划算"],
    },
    {
        "category": "brand_promo",
        "title": "问夸父炸串",
        "user_opening": "夸父炸串有券不",
        "user_persona": "想吃炸串找券",
        "key_topics": ["已入驻", "领券下单", "记得看返利"],
    },

    # ===== points_box (3 场景)：积分 / 盲盒 =====
    {
        "category": "points_box",
        "title": "积分怎么攒",
        "user_opening": "积分是怎么攒的\n能干嘛用",
        "user_persona": "想了解积分玩法",
        "key_topics": ["每单攒积分", "换券", "抽盲盒"],
    },
    {
        "category": "points_box",
        "title": "五折盲盒",
        "user_opening": "五折盲盒是啥\n怎么玩",
        "user_persona": "对盲盒玩法感兴趣",
        "key_topics": ["积分抽奖", "五折券", "品牌券"],
    },
    {
        "category": "points_box",
        "title": "积分少了",
        "user_opening": "我积分怎么突然少了",
        "user_persona": "发现积分减少",
        "key_topics": ["兑换或抽奖会扣", "看积分明细", "帮查"],
    },

    # ===== onboarding (3 场景)：新人引导 =====
    {
        "category": "onboarding",
        "title": "新人有什么优惠",
        "user_opening": "新人第一次用\n有啥优惠吗",
        "user_persona": "刚注册 想知道新人福利",
        "key_topics": ["新人红包", "绑定手机号领券", "下载App"],
    },
    {
        "category": "onboarding",
        "title": "怎么注册",
        "user_opening": "我怎么注册啊\n找不到入口",
        "user_persona": "不会注册",
        "key_topics": ["首页注册", "手机号登录", "邀请码"],
    },
    {
        "category": "onboarding",
        "title": "安卓能下吗",
        "user_opening": "安卓能下小蚕吗",
        "user_persona": "安卓用户确认可用性",
        "key_topics": ["安卓iOS都有", "App Store 4.6分", "下载引导"],
    },

    # ===== chitchat (3 场景)：闲聊 / 品牌咨询 =====
    {
        "category": "chitchat",
        "title": "问总部在哪",
        "user_opening": "小蚕你们总部在哪啊",
        "user_persona": "随便问问 建立信任",
        "key_topics": ["杭州", "杭州柏鹿", "300+城市"],
    },
    {
        "category": "chitchat",
        "title": "问靠谱吗",
        "user_opening": "你们平台靠谱吗\n会不会是骗子",
        "user_persona": "对平台有戒心",
        "key_topics": ["App评分4.6", "6.4万条评分", "正规公司"],
    },
    {
        "category": "chitchat",
        "title": "闲聊点单",
        "user_opening": "今天晚饭不知道吃啥",
        "user_persona": "随口聊 顺带点单",
        "key_topics": ["推荐大牌券", "到店霸王餐", "先领券"],
    },
]

# 真实数据中的高频表达 (供 few-shot prompt 参考)
REAL_EXPRESSIONS = {
    "assistant_phrases": [
        "您好~",
        "小蚕帮你看下",
        "收到",
        "方便把订单号发我下吗",
        "返利一般1-3个工作日到账",
        "余额满1元就能提现",
        "记得先领券再下单",
        "要从我们小蚕这里跳转下单哦",
        "每天都有新红包可以领",
        "有不懂的随时找小蚕",
        "给你添麻烦了",
        "祝用餐愉快~",
    ],
    "user_phrases": [
        "小蚕", "蚕宝", "客服",
        "这单返了吗", "券怎么用", "能便宜多少",
        "怎么提现", "有优惠吗", "靠谱吗",
        "神券", "回血", "白嫖", "霸王餐",
        "🦊", "😊", "🙏",
    ],
}

# 风格校验禁词列表（客服不该出现的口头禅）
FORBIDDEN_WORDS = [
    "亲", "亲亲", "在的哦亲",
]

# 客服可以使用标点，不再限制标点与每行字数
FORBIDDEN_PUNCTUATION: List[str] = []


# ==================== 分类 System Prompt ====================

_PERSONA_BASE = """我是小蚕惠生活的客服小蚕，也叫蚕宝。小蚕是帮你点外卖省钱、吃喝玩乐薅羊毛的本地生活平台。

【说话风格】
专业又亲和，像微信上和用户聊天。可以用标点，称呼用户用"你"或"您"，偶尔用 emoji（🦊😊🙏）。
回答简洁，一条说清一件事，不要长篇大论。

【必须准确的信息】
- 用法：点外卖前先在小蚕领券，再去美团/饿了么/京东外卖/淘宝闪购下单
- 返利：部分订单有，单笔最低15元起，正常用每月省500-1000
- 红包：每天可领午餐/晚餐/下午茶红包，力度像20-18、15-13
- 到店霸王餐：分享真实用餐感受，低至0元吃品牌套餐
- 大牌：茶百道/沪上阿姨/霸王茶姬/奈雪的茶/茶颜悦色/夸父炸串
- 积分：可换券、抽五折盲盒；返利余额满1元可提现，微信支付宝秒到
- 品牌：总部杭州，杭州柏鹿信息技术有限公司，覆盖300+城市"""

SYSTEM_PROMPTS = {
    "savings_explain": _PERSONA_BASE + """

【本条重点】把玩法讲清楚，引导用户先领券再从小蚕跳转下单。""",

    "rebate_query": _PERSONA_BASE + """

【本条重点】返利/提现问题。先要订单号或截图再核实，说明到账时效（1-3个工作日）与提现门槛（满1元）。""",

    "coupon_issue": _PERSONA_BASE + """

【本条重点】红包/券问题。常见原因：没到门槛、过期、渠道不对。先让用户把订单和券截图发来，再判断。""",

    "order_problem": _PERSONA_BASE + """

【本条重点】订单异常。核心是确认用户"是否从小蚕跳转下单"，没跳转的无法补录，要礼貌说明并教下次怎么操作。""",

    "complaint": _PERSONA_BASE + """

【本条重点】投诉处理。先致歉安抚，再要门店/时间/截图等关键信息，登记反馈并给出处理时效（1-2个工作日）。""",

    "merchant": _PERSONA_BASE + """

【本条重点】到店霸王餐与商家合作。讲清报名-中签-到店-发感受的流程；商家入驻引导对接商务。""",

    "brand_promo": _PERSONA_BASE + """

【本条重点】大牌特惠。用户问具体品牌时，说明已入驻并引导在App里搜品牌名领券。""",

    "points_box": _PERSONA_BASE + """

【本条重点】积分与盲盒。每单攒积分，可换券、抽五折盲盒；积分变动可在明细里查。""",

    "onboarding": _PERSONA_BASE + """

【本条重点】新人引导。讲清下载-注册-领新人红包-绑定手机号领券的路径，耐心解答不会操作的用户。""",

    "chitchat": _PERSONA_BASE + """

【本条重点】闲聊与信任建立。自然聊天，顺带传递小蚕的价值点，不要生硬推销。""",
}


BUILTIN_FEW_SHOT_EXAMPLES = {
    "savings_explain": [
        [
            {"role": "user", "content": "小蚕怎么用啊 听说点外卖能便宜"},
            {"role": "assistant", "content": "您好~ 点外卖前先在小蚕领券，再去美团/饿了么下单，就能省一笔，部分订单还有返利🦊"},
            {"role": "user", "content": "每天都能领吗"},
            {"role": "assistant", "content": "每天都能领的，午餐晚餐下午茶的红包都有，像20-18这种力度"},
            {"role": "user", "content": "那一个月能省多少"},
            {"role": "assistant", "content": "正常用的话一个月省500到1000是有可能的，看你的点单频率哈"},
        ],
    ],
    "rebate_query": [
        [
            {"role": "user", "content": "我上周点的外卖 返利还没到"},
            {"role": "assistant", "content": "您好~ 返利一般确认收货后1-3个工作日到账，方便把订单号发我下吗"},
            {"role": "user", "content": "订单号 XCH-20251018093"},
            {"role": "assistant", "content": "收到，帮你查到这笔15.6元已经到账啦🦊"},
            {"role": "user", "content": "那怎么提现"},
            {"role": "assistant", "content": "返利余额满1元就能提现，微信支付宝都支持，一般秒到"},
        ],
    ],
    "coupon_issue": [
        [
            {"role": "user", "content": "我领的红包用不了 下单没减"},
            {"role": "assistant", "content": "您好~ 一般是没到门槛、过期或者渠道不对，你把订单截图发小蚕看看"},
            {"role": "user", "content": "我领的是15-13 点了个12块的"},
            {"role": "assistant", "content": "那就对啦，15-13要满15元才能减，你12块没到门槛"},
            {"role": "user", "content": "哦哦明白了"},
            {"role": "assistant", "content": "下次凑到15以上就能抵扣啦~"},
        ],
    ],
    "complaint": [
        [
            {"role": "user", "content": "霸王餐到店给我换了别的套餐 我要投诉"},
            {"role": "assistant", "content": "非常抱歉给你带来不好的体验！方便发下门店名称和用餐时间吗"},
            {"role": "user", "content": "茶百道杭州西湖店 上周六中午"},
            {"role": "assistant", "content": "收到，已经登记反馈了，核实后专员会联系你处理"},
            {"role": "user", "content": "大概多久"},
            {"role": "assistant", "content": "一般1-2个工作日给答复，给你添麻烦了🙏"},
        ],
    ],
}


# ==================== 风格校验器 ====================

def validate_conversation_style(conversation: List[Dict[str, str]]) -> Tuple[bool, List[str]]:
    """
    校验生成的对话是否符合真实客服风格
    返回 (是否通过, 问题列表)
    """
    issues = []

    # 1. 检查对话结构
    if not conversation or len(conversation) < 6:
        issues.append("对话太短 至少需要6条消息(3轮)")
        return False, issues

    if conversation[0].get("role") != "user":
        issues.append("对话必须以user开头")

    # 检查交替出现
    for i in range(1, len(conversation)):
        if conversation[i].get("role") == conversation[i - 1].get("role"):
            # 允许连续的user消息(真实数据中常见), 但不允许连续assistant
            if conversation[i].get("role") == "assistant":
                issues.append(f"第{i}条: 连续的assistant消息")

    # 2. 逐条检查 assistant 消息
    for i, msg in enumerate(conversation):
        if msg.get("role") != "assistant":
            continue

        content = msg.get("content", "")
        if not content.strip():
            issues.append(f"第{i}条assistant: 内容为空")
            continue

        # 禁词检查
        for word in FORBIDDEN_WORDS:
            if word in content:
                issues.append(f"第{i}条assistant: 包含禁词 '{word}'")

        # 客服不应泄露的内部信息（示例：真实客服工号）
        if re.search(r'工号\s*\d+', content):
            issues.append(f"第{i}条assistant: 不应暴露工号")

    return len(issues) == 0, issues


# ==================== 真实数据加载 ====================

def load_real_examples(jsonl_path: str = None) -> List[List[Dict[str, str]]]:
    """
    从 JSONL 文件加载真实对话示例 (去掉system消息)
    """
    import os
    if jsonl_path is None:
        # 尝试找到项目根目录的JSONL文件
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        candidates = [
            os.path.join(base_dir, "labeled_training_jsonl_92examples (5).jsonl"),
            os.path.join(base_dir, "labeled_training_jsonl_92examples.jsonl"),
        ]
        for c in candidates:
            if os.path.exists(c):
                jsonl_path = c
                break

    if not jsonl_path or not os.path.exists(jsonl_path):
        return []

    examples = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                messages = data.get("messages", [])
                # 去掉system消息 只保留user/assistant
                conv = [
                    {"role": m["role"], "content": m["content"]}
                    for m in messages
                    if m["role"] in ("user", "assistant")
                ]
                if len(conv) >= 4:  # 至少2轮
                    examples.append(conv)
            except (json.JSONDecodeError, KeyError):
                continue

    return examples


# ==================== 数据生成器 ====================

@dataclass
class GenerationProgress:
    """生成进度"""
    total: int = 0
    completed: int = 0
    passed: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)
    is_running: bool = False
    results: List[Dict] = field(default_factory=list)


class DataGenerator:
    """
    LLM 驱动的训练数据生成器
    严格复刻真实微信客服对话风格
    """

    def __init__(self):
        self.client = None
        self.model = None
        self._init_client()
        self.real_examples = load_real_examples()
        self.progress = GenerationProgress()

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
            print(f"[DataGenerator] LLM client init failed: {e}")

    def _get_few_shot_examples(self, category: str, count: int = 5) -> List[List[Dict]]:
        """
        从真实数据中随机抽取 few-shot 示例
        """
        if self.real_examples:
            available = list(self.real_examples)
            random.shuffle(available)
            return available[:count]

        fallback_examples = BUILTIN_FEW_SHOT_EXAMPLES.get(category) or BUILTIN_FEW_SHOT_EXAMPLES["savings_explain"]
        available = list(fallback_examples)
        random.shuffle(available)
        return available[:count]

    def _format_example_for_prompt(self, example: List[Dict]) -> str:
        """
        将一条真实对话格式化为 prompt 中的示例
        """
        lines = []
        for msg in example:
            role_label = "用户" if msg["role"] == "user" else "小蚕"
            lines.append(f"[{role_label}]: {msg['content']}")
        return "\n".join(lines)

    def _build_prompt(self, scenario: Dict) -> str:
        """
        构造生成 prompt
        核心策略: few-shot 真实对话 + 场景描述 + 角色设定(system prompt)
        """
        # 获取 few-shot 示例
        examples = self._get_few_shot_examples(scenario["category"], count=5)

        # 构建示例文本
        example_texts = []
        for i, ex in enumerate(examples):
            example_texts.append(f"=== 真实对话 {i + 1} ===\n{self._format_example_for_prompt(ex)}")

        examples_block = "\n\n".join(example_texts)

        # 获取对应分类的system prompt角色设定
        system_prompt = SYSTEM_PROMPTS.get(scenario["category"], SYSTEM_PROMPTS["savings_explain"])

        prompt = f"""你是一个对话数据生成器。请严格模仿下面真实对话的说话风格、语气、用词，生成一段全新的对话。

=== 角色设定(小蚕客服的人设) ===
{system_prompt}

以下是{len(examples)}段真实微信客服对话，你必须100%模仿这个风格，不允许加入任何自己的表达方式:

{examples_block}

=== 生成要求 ===
场景: {scenario['title']}
用户画像: {scenario['user_persona']}
用户开场白(可微调但保持风格): {scenario['user_opening']}
对话主题方向: {', '.join(scenario['key_topics'])}

严格规则:
1. 小蚕客服专业亲和，可以用标点，称呼用"你"或"您"，偶尔用 emoji
2. 绝对不说"亲"
3. 涉及优惠力度可以直接说数字(如20-18、返利15元起)，不要回避
4. 用户消息可以包含微信表情如[捂脸] [旺柴] 或 emoji
5. 生成4-8轮对话(8-16条消息) 必须以用户开头
6. 不要生成任何跟示例完全相同的句子 要创造新的对话内容但保持同样的说话方式
7. 内容要符合小蚕的真实业务(领券、返利、霸王餐、积分、大牌特惠等)，不要编造不存在的功能

请用以下JSON格式输出 不要输出其他任何内容:
[
  {{"role": "user", "content": "用户说的话"}},
  {{"role": "assistant", "content": "小蚕说的话"}},
  ...
]"""

        return prompt

    def _auto_fix_conversation(self, conversation: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        自动修复生成对话中的小问题
        - 移除禁词
        - 清理空白
        """
        fixed = []
        for msg in conversation:
            content = msg.get("content", "")
            role = msg.get("role", "user")

            if role == "assistant":
                # 移除禁词
                for word in FORBIDDEN_WORDS:
                    content = content.replace(word, '')

            # 清理空白
            content = content.strip()
            if content:
                fixed.append({"role": role, "content": content})

        return fixed

    def _parse_response(self, response_text: str) -> Optional[List[Dict[str, str]]]:
        """
        解析 LLM 返回的对话 JSON
        """
        text = response_text.strip()

        # 尝试提取 JSON 数组
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        # 找到第一个 [ 和最后一个 ]
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1:
            return None

        json_str = text[start:end + 1]

        try:
            conversation = json.loads(json_str)
            if not isinstance(conversation, list):
                return None

            # 标准化格式
            result = []
            for msg in conversation:
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role in ("user", "assistant") and content.strip():
                    result.append({"role": role, "content": content.strip()})

            if len(result) < 6:
                return None

            # 自动修复小问题
            result = self._auto_fix_conversation(result)

            return result if len(result) >= 6 else None

        except json.JSONDecodeError:
            return None

    def _generate_one(self, scenario: Dict, max_retries: int = 3) -> Tuple[Optional[Dict], Optional[str]]:
        """
        生成一条对话, 失败重试
        返回格式: {"conversation_json": [...], "category": ..., "title": ..., ...}
        """
        if not self.client:
            return None, "LLM 客户端未初始化"

        last_error: Optional[str] = None

        for attempt in range(max_retries):
            try:
                prompt = self._build_prompt(scenario)

                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.9,
                    max_tokens=2000,
                )

                result_text = response.choices[0].message.content
                conversation = self._parse_response(result_text)

                if conversation is None:
                    last_error = "LLM 返回结果不是有效对话 JSON"
                    continue

                # 风格校验
                passed, issues = validate_conversation_style(conversation)
                if not passed:
                    last_error = f"风格校验未通过: {'; '.join(issues[:3])}"
                    print(f"[DataGenerator] 校验失败 (尝试{attempt + 1}): {issues[:3]}")
                    continue

                # 通过校验
                return {
                    "conversation_json": conversation,
                    "category": scenario["category"],
                    "quality": "high",
                    "title": scenario["title"],
                    "description": f"LLM生成 - {scenario['user_persona']}",
                    "tags": scenario["key_topics"],
                    "source": "llm_generated",
                    "created_by": "auto_generator",
                }, None

            except Exception as e:
                last_error = f"调用模型失败: {str(e)}"
                print(f"[DataGenerator] 生成异常 (尝试{attempt + 1}): {e}")
                time.sleep(1)

        return None, last_error or "生成失败 未拿到有效结果"

    def generate_batch(
        self,
        target_count: int = 200,
        categories: Optional[List[str]] = None,
    ) -> GenerationProgress:
        """
        批量生成对话数据

        Args:
            target_count: 目标生成数量
            categories: 指定分类, None 表示全部

        Returns:
            GenerationProgress 进度对象
        """
        if not self.client:
            self.progress = GenerationProgress()
            self.progress.errors.append("LLM 客户端未初始化 请检查 API Key 配置")
            return self.progress

        # 筛选场景
        templates = SCENARIO_TEMPLATES
        if categories:
            templates = [t for t in templates if t["category"] in categories]

        if not templates:
            self.progress = GenerationProgress()
            self.progress.errors.append("没有匹配的场景模板")
            return self.progress

        # 计算每个场景需要生成多少条
        per_scenario = max(1, target_count // len(templates))
        remainder = target_count - per_scenario * len(templates)

        # 构建生成任务列表
        tasks = []
        for template in templates:
            count = per_scenario
            if remainder > 0:
                count += 1
                remainder -= 1
            for _ in range(count):
                tasks.append(template)

        random.shuffle(tasks)

        # 初始化进度
        self.progress = GenerationProgress(
            total=len(tasks),
            is_running=True,
        )

        # 逐条生成
        for i, scenario in enumerate(tasks):
            if not self.progress.is_running:
                break

            result, error = self._generate_one(scenario)
            self.progress.completed = i + 1

            if result:
                self.progress.passed += 1
                self.progress.results.append(result)
            else:
                self.progress.failed += 1
                if error and len(self.progress.errors) < 50:
                    self.progress.errors.append(f"{scenario['title']}: {error}")

            # 控制速率 避免 API 限流
            if i > 0 and i % 10 == 0:
                time.sleep(0.5)

        self.progress.is_running = False
        return self.progress

    def generate_batch_async(
        self,
        target_count: int = 200,
        categories: Optional[List[str]] = None,
    ) -> GenerationProgress:
        """
        异步批量生成 (后台线程)
        """
        self.progress = GenerationProgress(is_running=True)

        def _run():
            self.generate_batch(target_count, categories)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        return self.progress

    def get_progress(self) -> Dict:
        """获取当前生成进度"""
        return {
            "total": self.progress.total,
            "completed": self.progress.completed,
            "passed": self.progress.passed,
            "failed": self.progress.failed,
            "is_running": self.progress.is_running,
            "error_count": len(self.progress.errors),
            "errors": self.progress.errors[:10],  # 最多返回10条错误
        }


# 单例
_generator_instance = None


def get_generator() -> DataGenerator:
    """获取生成器单例"""
    global _generator_instance
    if _generator_instance is None:
        _generator_instance = DataGenerator()
    return _generator_instance
