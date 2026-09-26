# -*- coding: utf-8 -*-
"""
对话状态追踪（DST）—— 多轮对话的「工作记忆」

对应教材 Ch5《多轮对话状态管理》：
  5.2.1 四层状态槽位（意图 / 实体 / 画像 / 阶段 + 系统状态）
  5.2.3 动态上下文注入（拿到订单号 → 立即查详情 → 注入后续所有轮次）
  5.3.1 共指消解（把前文实体注入 prompt，让 LLM 能消解"它/那个"）
  5.3.2 意图延续（"是的，发错货" 不是新意图，是对上一轮追问的回答）
  5.2.2 滑动窗口 + 对话摘要压缩

设计原则：**状态是唯一的真相来源**。LLM 每轮看到的 prompt 都由状态渲染而来，
因此"客户已经说过的信息"在结构上不可能丢失——这是根治"反复问订单号"的关键。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional

from app.services import order_store


# ==================== 对话阶段 ====================

class DialogPhase(str, Enum):
    """漏斗阶段：决定 Agent 这一轮"该做什么"，而不只是"该说什么" """
    INTAKE = "intake"                 # 刚接单
    INFO_GATHERING = "info_gathering"  # 收集缺失信息
    DIAGNOSIS = "diagnosis"           # 诊断问题
    SOLUTION = "solution"             # 给方案
    ACTION = "action"                 # 执行确认
    CLOSING = "closing"               # 收尾
    ESCALATION = "escalation"         # 转人工


PHASE_ACTION = {
    DialogPhase.INTAKE: "先共情接住客户诉求，判断是否需要查订单；不要一次性问多个问题。",
    DialogPhase.INFO_GATHERING: "只追问当前最关键的 1 个缺失槽位，其余信息不要问。",
    DialogPhase.DIAGNOSIS: "结合订单事实确认问题原因/责任方，不要重复要客户复述。",
    DialogPhase.SOLUTION: "给出明确方案（可退/不可退、金额、时效、谁承担运费），并询问客户是否确认。",
    DialogPhase.ACTION: "执行已确认的操作（发起退货/建单），回执单号与时效。",
    DialogPhase.CLOSING: "确认是否还有其他问题，简短收尾。",
    DialogPhase.ESCALATION: "说明正在转人工，并同步已登记的信息。",
}


# ==================== 意图延续矩阵（Ch5.3.2） ====================

# 同一业务流程内的合法延续：新意图不改变路由，只更新子意图
INTENT_CONTINUATIONS: Dict[str, set] = {
    # 退款流程中客户问订单/物流/商品细节，都属于同一业务流
    "refund_return": {"refund_return", "order_status", "logistics", "product_inquiry", "general_faq"},
    "logistics": {"logistics", "order_status"},
    "order_status": {"order_status", "logistics"},
    # 投诉是独立处理链路：客户从"骂人"转到"我要退款"，属于话题切换，必须重新路由
    "complaint": {"complaint"},
    "product_inquiry": {"product_inquiry", "general_faq"},
    "general_faq": {"general_faq", "product_inquiry"},
}

# 回答型消息：客户在回应追问，而不是提出了新话题
_ANSWER_PREFIX = (
    "是的", "是", "对", "对的", "嗯", "好", "好的", "可以", "行", "没问题",
    "不是", "没有", "有", "确认", "确定", "ok", "OK", "是的，", "对，",
)

# 祈使句 / 明确新诉求：即使很短也不是"回答"，而是新的意图表达
_REQUEST_SIGNALS = (
    "给我", "我要", "我想", "帮我", "麻烦你", "退还", "退钱", "退款", "退货", "换货",
    "查一下", "查查", "投诉", "赔", "投诉你们",
)

# 订单号遗忘信号（Ch5.2.3 反模式：客户给不出标识时，系统必须自己查）
_ORDER_UNKNOWN_RE = re.compile(
    r"(订单号|单号|订单)[^，。,.!?？]{0,6}(忘|记不|不记得|想不起|找不到|没了|丢了|不知道)"
    r"|(忘|记不|不记得|想不起|找不到)[^，。,.!?？]{0,6}(订单号|单号)"
)

# 订单号：GM20250803-1287 / 任意「字母+数字(-数字)」形态
# 注意：不能用 \b —— 中文属于 \w，"订单GM2025..." 里 单/G 之间没有词边界，
# 会导致客户把单号粘在中文后面时抽不出来（真实语料里极常见）。
_ORDER_ID_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z]{2,5}\d{6,12}(?:-\d{2,6})?)(?![0-9A-Za-z])"
)

# 退货/退款原因
_REASON_PATTERNS = [
    (r"发错货|发错|寄错|错发|货不对板|与描述不符|实物不符", "发错货/与描述不符"),
    (r"质量问题|有质量问题|坏了|破损|摔坏|故障|不能用|用不了|无法使用", "质量问题"),
    (r"漏发|少发|缺件|少件|少东西", "漏发少发"),
    (r"过期|临期|变质|发霉|不新鲜", "过期变质"),
    (r"未收到|没收到|一直没到|没送", "未收到货"),
    (r"不喜欢|不想要|买错|买多了|误购|重复下单|重复支付|多付", "不想要/买错"),
    (r"尺码|大小不合适|不合适|尺寸不对", "尺码不合适"),
]

# 客户选号（配合"最近订单候选列表"）
_SELECTION_RE = re.compile(r"^\s*(?:第)?\s*([1-9])\s*(?:个|单|笔|号)?\s*[。.!！]?\s*$")

_PRODUCT_HINT_RE = re.compile(
    r"[\u4e00-\u9fa5A-Za-z0-9]{1,8}(?:红包券|红包|代金券|优惠券|体验券|年卡|会员卡|月卡|套餐|盲盒|团购券)"
)

# 追问槽位检测：从 Agent 的回复里识别它到底问了什么
_ASK_HINTS = {
    "order_id": ("订单号", "单号"),
    "refund_reason": ("什么原因", "退货原因", "退款原因", "为什么退", "原因"),
    "issue_desc": ("具体是什么问题", "什么问题", "具体情况", "什么情况"),
    "product_name": ("什么商品", "哪个商品", "买的什么"),
}


# ==================== 状态对象 ====================

@dataclass
class DialogState:
    session_id: str = ""
    user_id: Optional[str] = None

    # ---- 第一层：意图状态 ----
    current_intent: Optional[str] = None
    sub_intent: Optional[str] = None
    intent_confidence: float = 0.0
    intent_trail: List[str] = field(default_factory=list)

    # ---- 第二层：实体状态 ----
    order_id: Optional[str] = None
    order_snapshot: Dict[str, Any] = field(default_factory=dict)
    product_name: Optional[str] = None
    issue_desc: Optional[str] = None
    refund_reason: Optional[str] = None
    order_amount: Optional[float] = None
    refund_eligible: Optional[bool] = None
    refund_rule: Optional[str] = None
    shipping_fee_bearer: Optional[str] = None
    order_unknown: bool = False                 # 客户表示"忘了订单号"
    recent_orders: List[Dict[str, Any]] = field(default_factory=list)

    # ---- 第三层：用户画像 ----
    user_tier: str = "normal"
    order_count: int = 0

    # ---- 第四层：阶段 + 系统状态 ----
    phase: str = DialogPhase.INTAKE.value
    turn_count: int = 0
    asked_slots: List[str] = field(default_factory=list)     # 已追问过的槽位
    answered_slots: List[str] = field(default_factory=list)  # 已被客户回答/已填充
    last_question_slot: Optional[str] = None
    conversation_summary: Optional[str] = None
    rag_context: Optional[str] = None

    # ---------- 序列化 ----------
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "DialogState":
        if not data:
            return cls()
        allowed = {f for f in cls.__dataclass_fields__}  # noqa: RUF100
        return cls(**{k: v for k, v in data.items() if k in allowed})

    # ---------- 实体更新 ----------
    def update_entity(self, name: str, value: Any) -> bool:
        """写入槽位；返回是否为新值（供"本轮新获得信息"判定）"""
        if value in (None, "", [], {}):
            return False
        old = getattr(self, name, None)
        if old == value:
            return False
        setattr(self, name, value)
        if name not in self.answered_slots:
            self.answered_slots.append(name)
        return True

    # ---------- 槽位完整度 ----------
    def missing_slots(self) -> List[str]:
        need: List[str] = []
        intent = self.current_intent
        # 客户已表示记不清订单号且有候选单 → 订单号不再是"要追问的槽位"，
        # 改用候选列表让客户确认（否则会出现"禁止再问订单号"和"请追问订单号"自相矛盾）
        order_unknown_with_candidates = self.order_unknown and bool(self.recent_orders)
        if intent in ("refund_return", "logistics", "order_status", "complaint"):
            if not self.order_id and not order_unknown_with_candidates:
                need.append("order_id")
        if intent == "refund_return":
            if not self.refund_reason and not self.issue_desc:
                need.append("refund_reason")
        elif intent == "complaint":
            if not self.issue_desc:
                need.append("issue_desc")
        return need

    def is_refund_ready(self) -> bool:
        return bool(self.order_id and (self.refund_reason or self.issue_desc))

    def compute_phase(self, suggest_transfer: bool = False) -> str:
        if suggest_transfer:
            return DialogPhase.ESCALATION.value
        if self.current_intent == "refund_return":
            if self.refund_eligible is False:
                return DialogPhase.SOLUTION.value
            if self.is_refund_ready():
                return DialogPhase.ACTION.value
            return DialogPhase.INFO_GATHERING.value
        if self.current_intent in ("logistics", "order_status"):
            return DialogPhase.SOLUTION.value if self.order_id else DialogPhase.INFO_GATHERING.value
        if self.current_intent == "complaint":
            return DialogPhase.DIAGNOSIS.value if self.issue_desc else DialogPhase.INFO_GATHERING.value
        if self.current_intent:
            return DialogPhase.SOLUTION.value
        return DialogPhase.INTAKE.value

    # ---------- prompt 渲染 ----------
    def to_context_string(self) -> str:
        """
        渲染成可注入 prompt 的状态块（Ch5.2.1 to_context_string）

        按需注入：只输出与当前阶段相关的槽位，避免 prompt 膨胀。
        """
        lines: List[str] = []

        known: List[str] = []
        if self.order_id:
            snap = self.order_snapshot or {}
            detail = ""
            if snap:
                detail = (
                    f"（{snap.get('product_name')} / ¥{float(snap.get('amount') or 0):.2f}"
                    f" / {snap.get('status')}"
                    f" / 物流 {snap.get('logistics_company') or '-'} {snap.get('logistics_no') or '-'}）"
                )
            elif self.order_id:
                detail = "（⚠️ 系统按此单号未查到订单，不要编造商品信息；请提示客户核对单号，或提供下单手机号后四位/商品名）"
            known.append(f"- 订单号：{self.order_id}{detail} —— 已确认，**禁止再向客户索要订单号**")
        if self.product_name:
            known.append(f"- 商品：{self.product_name}")
        if self.issue_desc:
            known.append(f"- 问题描述：{self.issue_desc}")
        if self.refund_reason:
            known.append(f"- 退款原因：{self.refund_reason}")
        if self.refund_eligible is not None:
            verdict = "符合退款条件" if self.refund_eligible else "不符合无理由退款条件"
            known.append(f"- 退款资格：{verdict}（{self.refund_rule or ''}）")
        if self.shipping_fee_bearer:
            known.append(f"- 运费承担：{self.shipping_fee_bearer}")

        if known:
            lines.append("【已知信息｜直接使用，禁止重复询问】")
            lines.extend(known)

        missing = self.missing_slots()
        if missing:
            cn = {"order_id": "订单号", "refund_reason": "退款原因", "issue_desc": "问题描述"}
            lines.append("【本轮缺失信息｜最多追问 1 项】" + "、".join(cn.get(m, m) for m in missing))
        else:
            lines.append("【本轮缺失信息】无，不要再问任何已知信息，直接推进方案")

        if self.answered_slots:
            cn = {
                "order_id": "订单号", "refund_reason": "退款原因", "issue_desc": "问题描述",
                "product_name": "商品", "recent_orders": "订单候选",
            }
            done = [cn.get(s, s) for s in self.answered_slots]
            lines.append("【客户已回答｜同一问题禁止再问】" + "、".join(done))

        if self.order_unknown and not self.order_id and self.recent_orders:
            lines.append("【客户已表示记不清订单号｜禁止再要订单号】请从下列已查到的订单中让客户确认是哪一单：")
            for i, o in enumerate(self.recent_orders, 1):
                lines.append("  " + order_store.brief(o, i))

        if self.conversation_summary:
            lines.append(f"【前序对话摘要】{self.conversation_summary}")

        try:
            phase_enum = DialogPhase(self.phase)
        except ValueError:
            phase_enum = DialogPhase.INTAKE
        lines.append(
            f"【当前阶段】{phase_enum.value}（第 {self.turn_count} 轮）→ "
            f"{PHASE_ACTION.get(phase_enum, '')}"
        )
        return "\n".join(lines)


# ==================== 意图延续 ====================

_IDENTIFIER_ONLY_RE = re.compile(r"^[\sA-Za-z0-9\-—_]{4,}$")


def _is_identifier_only(msg: str) -> bool:
    """只回了一串编号（纯数字或字母数字混合）：必须含数字，避免把 "sb" 这类词误判成单号"""
    return bool(_IDENTIFIER_ONLY_RE.match(msg)) and bool(re.search(r"\d", msg))


def is_followup_answer(message: str) -> bool:
    """判断消息是否是「回应追问」而非提出新话题"""
    msg = (message or "").strip()
    if not msg:
        return False
    # 只发了一串编号（"123432142" / "GM2025..."）→ 明显是在补充上一轮追问的单号
    if _is_identifier_only(msg):
        return True
    # 祈使句 / 明确诉求 → 是新意图表达，不算"回答"
    if any(s in msg for s in _REQUEST_SIGNALS):
        return False
    if any(msg.startswith(p) for p in _ANSWER_PREFIX):
        return True
    # 极短句（"发错货" / "质量问题"）通常是补充上一个问题
    if len(msg) <= 10 and not re.search(r"[?？]|怎么|如何|为什么|能不能|可以吗|多久", msg):
        return True
    return False


# 投诉的「升级信号」：只有出现这些词，才认为客户真的在投诉/要求追责，
# 而不是在已开业务流里补充一句抱怨（Ch5.3.2：话题切换必须有显式信号）
_COMPLAINT_ESCALATION_SIGNALS = (
    "投诉", "举报", "曝光", "差评", "12315", "消协", "工商", "起诉", "律师",
    "退一赔", "赔偿", "道歉", "人工", "经理", "主管", "上级", "领导",
    "骗子", "垃圾", "恶心", "滚", "sb", "傻逼", "太差", "什么破",
)

# 这些意图已经进入「具体业务流」，中途的情绪表达不应打断流程
_TASK_INTENTS = {"refund_return", "logistics", "order_status", "product_inquiry"}


def check_intent_continuation(current_intent: Optional[str], new_intent: Optional[str],
                              message: str) -> str:
    """
    返回 'continue' | 'switch'

    - continue：保持 current_intent（只更新 sub_intent），路由不变
    - switch：客户确实切换了话题
    """
    if not current_intent or not new_intent:
        return "switch"
    if current_intent == new_intent:
        return "continue"
    # 客户只回了一串编号 → 是在补充上一轮追问的标识，不管分类器怎么判都延续
    if _is_identifier_only((message or "").strip()):
        return "continue"
    # 业务流中途被分类成 complaint，但没有任何投诉升级信号
    # （例：退款流程中回"就是和我下单的不一样，我拍的是双人餐"）
    # → 这只是补充原因，不能把路由切到投诉 Agent，否则会重复开单、重复追问。
    if (new_intent == "complaint" and current_intent in _TASK_INTENTS
            and not any(s in (message or "") for s in _COMPLAINT_ESCALATION_SIGNALS)):
        return "continue"
    allowed = INTENT_CONTINUATIONS.get(current_intent, set())
    if new_intent in allowed and is_followup_answer(message):
        return "continue"
    if new_intent in allowed - {"logistics", "order_status"}:
        return "continue"
    return "switch"


def apply_intent_continuation(dst: "DialogState", new_intent: str,
                              message: str) -> str:
    """
    把「意图延续」规则落到状态上，返回最终用于路由的意图。

    两个引擎（LangGraph / deepagents）共用这一份逻辑，避免行为漂移。
    """
    prev = dst.current_intent
    if prev and prev != new_intent and check_intent_continuation(prev, new_intent, message) == "continue":
        dst.intent_trail.append(new_intent)
        dst.sub_intent = new_intent      # 子意图记录"客户当下在问什么"
        dst.current_intent = prev
        return prev
    dst.current_intent = new_intent
    return new_intent


# ==================== 实体抽取 ====================

def extract_entities(message: str, state: DialogState) -> Dict[str, Any]:
    """
    规则抽取（毫秒级、可解释），返回本轮新填入的槽位

    教材 Ch5.4 用 LLM 做 NER；工程上先用规则兜住高频槽位（订单号/原因/选号），
    LLM 抽取作为补充（见 llm_extract_entities），避免每轮都多花一次调用。
    """
    msg = (message or "").strip()
    new: Dict[str, Any] = {}

    # 1) 订单号遗忘信号
    if _ORDER_UNKNOWN_RE.search(msg):
        state.order_unknown = True
        new["order_unknown"] = True

    # 2) 订单号
    m = _ORDER_ID_RE.search(msg)
    if m:
        oid = m.group(1).upper()
        if state.update_entity("order_id", oid):
            new["order_id"] = oid
        state.order_unknown = False

    # 3) 客户从候选列表里选号（"2" / "第二个"）
    if not m and state.recent_orders:
        sel = _SELECTION_RE.match(msg)
        if sel:
            idx = int(sel.group(1)) - 1
            if 0 <= idx < len(state.recent_orders):
                oid = state.recent_orders[idx]["order_id"]
                if state.update_entity("order_id", oid):
                    new["order_id"] = oid
                state.order_unknown = False

    # 4) 退款/退货原因（直接作为问题描述）
    for pattern, label in _REASON_PATTERNS:
        if re.search(pattern, msg):
            if state.update_entity("refund_reason", label):
                new["refund_reason"] = label
            if state.update_entity("issue_desc", label):
                new["issue_desc"] = label
            break

    # 5) 商品名（只保留明显是商品/权益的名词，避免把口语当商品）
    if not state.product_name:
        pm = _PRODUCT_HINT_RE.search(msg)
        if pm:
            cand = pm.group(0)
            if state.update_entity("product_name", cand):
                new["product_name"] = cand

    return new


def detect_selected_order(message: str, state: DialogState) -> Optional[Dict[str, Any]]:
    """已选号 → 返回候选订单对象"""
    if not state.order_id:
        return None
    for o in state.recent_orders:
        if o.get("order_id") == state.order_id:
            return o
    return order_store.get_order(state.order_id)


def enrich_order_context(state: DialogState) -> Dict[str, Any]:
    """
    动态上下文注入（Ch5.2.3）：一次查清，全程复用

    - 有订单号且未取过详情 → 查订单，填充商品/金额/退款资格
    - 客户忘了订单号 → 拉最近订单候选，交给客户确认（而不是反复追问）
    """
    changed: Dict[str, Any] = {}

    if state.order_id and not state.order_snapshot:
        order = order_store.get_order(state.order_id)
        if order:
            state.order_snapshot = order_store.snapshot(order)
            changed["order_snapshot"] = True
            state.update_entity("product_name", order.get("product_name"))
            state.order_amount = order.get("amount")
            verdict = order_store.evaluate_refund(order)
            state.refund_eligible = verdict["eligible"]
            state.refund_rule = verdict["reason"]
            changed["refund_eligible"] = verdict["eligible"]
        else:
            # 订单号格式对但查不到 → 标记，让 Agent 说明并提供兜底
            state.order_snapshot = {}
            changed["order_not_found"] = True

    if state.order_unknown and not state.order_id:
        candidates = order_store.list_recent_orders(state.user_id, limit=3)
        if candidates:
            state.recent_orders = candidates
            changed["recent_orders"] = len(candidates)

    return changed


def record_asked_slots(answer: str, state: DialogState) -> None:
    """从 Agent 回复里识别它追问了哪个槽位，写入 asked_slots（用于下一轮"禁止重复问"）"""
    if not answer:
        return
    is_question = ("？" in answer or "?" in answer or "请提供" in answer
                   or "麻烦" in answer or "告诉我" in answer)
    if not is_question:
        return
    for slot, hints in _ASK_HINTS.items():
        if any(h in answer for h in hints):
            if slot not in state.asked_slots:
                state.asked_slots.append(slot)
            state.last_question_slot = slot
            break


def needs_repair(answer: str, state: DialogState) -> Optional[str]:
    """
    回复质量闸门：检测「又问了已知信息」这一类破坏上下文连续性的回复。

    返回违规描述；无违规则返回 None。命中时调用方会用一次低成本改写修正。
    """
    if not answer:
        return None
    is_question = ("？" in answer or "?" in answer or "请提供" in answer
                   or "麻烦" in answer)
    if not is_question:
        return None
    if state.order_id and ("订单号" in answer or "订单编号" in answer):
        return "客户已提供订单号，回复中却又索要订单号"
    if state.refund_reason and ("什么原因" in answer or "退货原因" in answer
                               or "退款原因" in answer):
        return "客户已说明原因，回复中却又追问原因"
    if state.order_unknown and not state.order_id and state.recent_orders and "订单号" in answer:
        return "客户已表示记不清订单号，回复中仍索要订单号（应让客户从候选订单中确认）"
    return None


# ==================== 滑动窗口 / 摘要 ====================

def window_size_for(intent: Optional[str]) -> int:
    """自适应窗口（Ch5.5）：FAQ 2 轮，交易类 5 轮，投诉 6 轮"""
    if intent == "complaint":
        return 6
    if intent in ("refund_return", "logistics", "order_status"):
        return 5
    return 2


def trim_history(history: List[Dict[str, str]], intent: Optional[str]) -> List[Dict[str, str]]:
    """按意图裁剪滑动窗口（保留最近 N 轮 = 2N 条消息）"""
    if not history:
        return []
    keep = window_size_for(intent) * 2
    return history[-keep:]


# ==================== 持久化 ====================

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS dialog_states (
    session_id   VARCHAR(128) PRIMARY KEY,
    state_json   TEXT NOT NULL,
    turn_count   INTEGER DEFAULT 0,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""


def _ensure_table(engine) -> None:
    from sqlalchemy import text
    try:
        with engine.begin() as conn:
            conn.execute(text(_CREATE_SQL))
    except Exception as e:  # 建表失败不应阻断对话
        print(f"[DialogState] 建表失败: {e}")


def load_state(db, session_id: str) -> DialogState:
    """按会话加载 DST；不存在则返回空状态（Ch5.2.5.1 状态持久化与恢复）"""
    if db is None or not session_id:
        return DialogState(session_id=session_id)
    from sqlalchemy import text
    try:
        _ensure_table(db.get_bind())
        row = db.execute(
            text("SELECT state_json FROM dialog_states WHERE session_id=:sid"),
            {"sid": session_id},
        ).fetchone()
        if row and row[0]:
            return DialogState.from_dict(json.loads(row[0]))
    except Exception as e:
        print(f"[DialogState] 加载失败: {e}")
    return DialogState(session_id=session_id)


def save_state(db, state: DialogState) -> None:
    if db is None or not state.session_id:
        return
    from sqlalchemy import text
    payload = json.dumps(state.to_dict(), ensure_ascii=False)
    try:
        _ensure_table(db.get_bind())
        updated = db.execute(
            text("UPDATE dialog_states SET state_json=:s, turn_count=:t, updated_at=CURRENT_TIMESTAMP "
                 "WHERE session_id=:sid"),
            {"s": payload, "t": state.turn_count, "sid": state.session_id},
        ).rowcount
        if not updated:
            db.execute(
                text("INSERT INTO dialog_states (session_id, state_json, turn_count, updated_at) "
                     "VALUES (:sid, :s, :t, CURRENT_TIMESTAMP)"),
                {"sid": state.session_id, "s": payload, "t": state.turn_count},
            )
        db.commit()
    except Exception as e:
        print(f"[DialogState] 保存失败: {e}")
        try:
            db.rollback()
        except Exception:
            pass


# ==================== LLM 实体抽取（补充） ====================

_LLM_EXTRACT_PROMPT = """你是客服对话信息抽取器。从客户消息中抽取结构化信息，只输出 JSON。

客户消息：{message}
已知订单号：{order_id}

输出字段（未提及填 null，不要猜）：
- order_id: 订单号（字母+数字，如 XX20250803-1287）
- refund_reason: 退货/退款原因（短语，如"发错货""质量问题""不想要了"）
- issue_desc: 问题描述（一句话）
- product_name: 商品名称

严格输出 JSON，不要任何解释。"""


def llm_extract_entities(message: str, state: DialogState) -> Dict[str, Any]:
    """LLM 兜底抽取（规则没抽到、且消息有一定信息量时才调用）"""
    msg = (message or "").strip()
    if len(msg) < 4 or not re.search(r"[\u4e00-\u9fa5]", msg):
        return {}
    try:
        from app.services.quiz import _get_llm_client
        client, model = _get_llm_client()
        if client is None:
            return {}
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": _LLM_EXTRACT_PROMPT.format(
                message=msg, order_id=state.order_id or "无")}],
            temperature=0.0,
            max_tokens=160,
        )
        raw = (resp.choices[0].message.content or "").strip()
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return {}
        data = json.loads(m.group(0))
    except Exception as e:
        print(f"[DialogState] LLM 抽取失败: {e}")
        return {}

    new: Dict[str, Any] = {}
    oid = (data.get("order_id") or "").strip().upper()
    if oid and re.match(r"^[A-Z]{2,5}\d{6,12}(-\d{2,6})?$", oid):
        if state.update_entity("order_id", oid):
            new["order_id"] = oid
    if data.get("refund_reason") and state.update_entity("refund_reason", data["refund_reason"]):
        new["refund_reason"] = data["refund_reason"]
    if data.get("issue_desc") and state.update_entity("issue_desc", data["issue_desc"]):
        new["issue_desc"] = data["issue_desc"]
    if data.get("product_name") and not state.product_name:
        if state.update_entity("product_name", data["product_name"]):
            new["product_name"] = data["product_name"]
    return new
