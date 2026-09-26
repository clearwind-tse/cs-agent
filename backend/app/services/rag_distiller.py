# -*- coding: utf-8 -*-
"""
RAG 知识蒸馏服务

将多段同类小蚕客服对话通过 LLM 蒸馏为标准化知识条目。

核心思路：
1. 按 intent 对已有 Q&A 分组
2. 每组取代表性对话 → LLM 蒸馏为 1 条标准知识
3. 与手写知识库合并去重（手写优先）
4. 输出高质量 RAG 知识条目

用法：
    from app.services.rag_distiller import RagDistiller
    distiller = RagDistiller()
    results, stats = distiller.batch_distill(entries, include_knowledge_base=True)
"""
import json
import re
import logging
from collections import defaultdict
from typing import List, Dict, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from app.config import get_settings
from app.services.rag_rewriter import infer_intent, infer_tags, infer_source

settings = get_settings()
logger = logging.getLogger(__name__)


# ==================== 蒸馏 Prompt ====================

DISTILL_PROMPT = """你是一个知识库数据工程师。你的任务是从多段小蚕惠生活客服对话中**蒸馏出一条标准知识条目**。

## 背景
以下是 {count} 段关于「{intent}」的真实用户咨询对话。每段包含用户问题 (Q) 和小蚕客服回答 (A)。

## 对话原文
{conversations}

## 蒸馏规则

### question（标准化问题）
- 提炼出用户最核心的问题（一句话，10-30字）
- 用清晰的疑问句表达，不要口语碎片
- 示例：✅ "外卖返利一般多久到账？" ❌ "小蚕 问一下 返利啥时候到"

### answer（结构化知识回答）
- 从多段对话中提取**共性信息**，合并为完整回答
- 用自然语言段落或编号列表组织（不是碎片短行）
- 包含具体数据和事实（红包力度、返利比例、到账时间、活动门槛等）
- 语气自然专业，客服口吻（可称"您"，不要"亲"、"亲亲"等）
- 不要包含时效性内容（活动截止日期、名额提醒等）
- 不要包含操作性内容（加微信、发订单号截图等）
- 每行不少于20字，总长度100-300字

### variants（问法变体）
- 生成 3-5 个用户可能的不同问法
- 包含口语、书面语、关键词搜索等多种形式
- 示例：["返利多久到账", "返利什么时候到", "返利到账时间"]

### 其他字段
- intent: 从对话内容判断的意图类别
- tags: 3-5个关键标签
- source: 从以下选一个最匹配的来源：
  红包优惠券规则、返利与提现规则、霸王餐参与规则、外卖下单流程、订单问题处理手册、积分盲盒玩法、品牌活动说明、新手指南、售后与投诉处理

## 输出格式
严格按以下 JSON 输出，不要输出其他内容:
{{
  "question": "标准化问题",
  "answer": "结构化知识回答（多行，100-300字）",
  "variants": ["问法1", "问法2", "问法3"],
  "intent": "意图分类",
  "tags": ["标签1", "标签2", "标签3"],
  "source": "来源"
}}"""


# ==================== 分组逻辑 ====================

def group_by_intent(entries: List[Dict], max_per_group: int = 10) -> Dict[str, List[Dict]]:
    """
    按 intent 分组聚合同类对话

    对没有 intent 的条目，使用 infer_intent 推断。
    每组最多保留 max_per_group 条（取 answer 最长的，信息量最大）。

    :param entries: RAG 条目列表 [{question, answer, category, ...}]
    :param max_per_group: 每组最大条目数
    :return: { intent: [entries] }
    """
    groups: Dict[str, List[Dict]] = defaultdict(list)

    for entry in entries:
        q = entry.get("question", "")
        a = entry.get("answer", "")

        # 复用现有的 intent 或重新推断
        intent = entry.get("intent", "")
        if not intent or intent == "一般咨询":
            intent = infer_intent(q, a)

        groups[intent].append(entry)

    # 每组按 answer 长度降序，取前 max_per_group 条
    result = {}
    for intent, items in groups.items():
        sorted_items = sorted(items, key=lambda x: len(x.get("answer", "")), reverse=True)
        result[intent] = sorted_items[:max_per_group]

    return result


# ==================== 手写知识库加载 ====================

def load_knowledge_base() -> List[Dict]:
    """
    加载 build_dual_rag.py 中的手写知识库

    :return: KNOWLEDGE_BASE 列表
    """
    try:
        import importlib.util
        import os

        # 定位 build_dual_rag.py
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        script_path = os.path.join(project_root, "scripts", "build_dual_rag.py")

        if not os.path.exists(script_path):
            logger.warning(f"[Distiller] 手写知识库文件不存在: {script_path}")
            return []

        spec = importlib.util.spec_from_file_location("build_dual_rag", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        kb = getattr(module, "KNOWLEDGE_BASE", [])
        logger.info(f"[Distiller] 加载手写知识库: {len(kb)} 条")
        return kb

    except Exception as e:
        logger.error(f"[Distiller] 加载手写知识库失败: {e}")
        return []


def get_covered_intents(knowledge_base: List[Dict]) -> set:
    """
    获取手写知识库已覆盖的 intent 集合

    :param knowledge_base: KNOWLEDGE_BASE 列表
    :return: 已覆盖的 intent 集合
    """
    return {item.get("intent", "") for item in knowledge_base if item.get("intent")}


# ==================== 合并逻辑 ====================

def merge_with_knowledge_base(
    distilled: List[Dict],
    knowledge_base: List[Dict],
) -> List[Dict]:
    """
    将蒸馏结果与手写知识库合并（手写优先）

    策略：
    1. 手写知识库全量保留（含 variants 展开）
    2. 蒸馏结果中，intent 已被手写覆盖的直接跳过
    3. 未覆盖的蒸馏结果追加

    :param distilled: LLM 蒸馏的知识条目
    :param knowledge_base: 手写知识库
    :return: 合并后的知识条目列表
    """
    covered_intents = get_covered_intents(knowledge_base)

    merged = []

    # 1. 手写知识库全量保留
    for item in knowledge_base:
        merged.append({
            "question": item["question"],
            "answer": item["answer"].strip(),
            "intent": item.get("intent", ""),
            "tags": item.get("tags", []),
            "source": item.get("source", ""),
            "variants": item.get("variants", []),
            "confidence": 1.0,  # 手写知识最高置信度
            "content_type": "knowledge",
            "category": "knowledge_base",
            "origin": "manual",
        })

    # 2. 蒸馏结果：跳过已覆盖的 intent
    added = 0
    skipped = 0
    for item in distilled:
        intent = item.get("intent", "")
        if intent in covered_intents:
            skipped += 1
            continue
        item["origin"] = "distilled"
        merged.append(item)
        added += 1

    logger.info(
        f"[Distiller] 合并结果: 手写={len(knowledge_base)}, "
        f"蒸馏新增={added}, 蒸馏跳过(已覆盖)={skipped}, "
        f"总计={len(merged)}"
    )

    return merged


# ==================== 蒸馏器 ====================

class RagDistiller:
    """RAG 知识蒸馏器"""

    def __init__(self):
        self.client = None
        self.model = None
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
            logger.error(f"[Distiller] LLM client init failed: {e}")

    def distill_group(self, intent: str, entries: List[Dict]) -> Optional[Dict]:
        """
        对同一 intent 的多段对话进行知识蒸馏

        :param intent: 意图分类（如 "返利查询"）
        :param entries: 同 intent 的对话条目列表
        :return: 蒸馏后的标准知识条目，失败返回 None
        """
        if not self.client:
            logger.warning("[Distiller] LLM 未初始化，使用规则回退")
            return self._rule_fallback(intent, entries)

        # 构建对话文本块
        conv_blocks = []
        for i, entry in enumerate(entries[:8], 1):  # 最多取 8 段
            q = entry.get("question", "").strip()
            a = entry.get("answer", "").strip()
            if q and a:
                conv_blocks.append(f"--- 对话 {i} ---\nQ: {q}\nA: {a}")

        if not conv_blocks:
            return None

        conversations_text = "\n\n".join(conv_blocks)

        prompt = DISTILL_PROMPT.format(
            count=len(conv_blocks),
            intent=intent,
            conversations=conversations_text,
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个专业的知识库数据工程师，擅长从非结构化对话中蒸馏出标准化知识。"
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=1000,
            )

            text = response.choices[0].message.content.strip()
            result = self._parse_distill_response(text)
            if result:
                result["confidence"] = 0.85  # 蒸馏知识的默认置信度
                result["content_type"] = "knowledge"
                result["category"] = intent
                logger.info(f"[Distiller] 蒸馏成功: intent={intent}, Q={result['question'][:30]}...")
            return result

        except Exception as e:
            logger.error(f"[Distiller] LLM 蒸馏失败 (intent={intent}): {e}")
            return self._rule_fallback(intent, entries)

    def _parse_distill_response(self, text: str) -> Optional[Dict]:
        """解析 LLM 蒸馏结果"""
        # 提取 JSON
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return None

        try:
            result = json.loads(text[start:end + 1])

            # 验证必需字段
            if not result.get("question") or not result.get("answer"):
                return None

            # 标准化
            result.setdefault("intent", "")
            result.setdefault("tags", [])
            result.setdefault("source", "微信咨询对话")
            result.setdefault("variants", [])

            # 确保 tags 是列表
            if isinstance(result["tags"], str):
                result["tags"] = [t.strip() for t in result["tags"].split(",")]

            # 确保 variants 是列表
            if isinstance(result["variants"], str):
                result["variants"] = [v.strip() for v in result["variants"].split(",")]

            return result

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[Distiller] JSON 解析失败: {e}")
            return None

    def _rule_fallback(self, intent: str, entries: List[Dict]) -> Optional[Dict]:
        """
        规则回退：当 LLM 不可用时，从同组对话中选择最佳条目

        策略：选 answer 最长（信息量最大）的一条，做基础清理
        """
        if not entries:
            return None

        # 选最长的 answer
        best = max(entries, key=lambda x: len(x.get("answer", "")))
        q = best.get("question", "").strip()
        a = best.get("answer", "").strip()

        if not q or not a:
            return None

        # 基础问题清理：去称呼、去表情
        q = re.sub(r'^(小蚕|蚕宝|客服|你好小蚕)[，,\s]*', '', q).strip()
        q = re.sub(r'\[[\u4e00-\u9fa5]+\]', '', q).strip()

        return {
            "question": q,
            "answer": a,
            "intent": intent,
            "tags": infer_tags(q, a),
            "source": infer_source(q, a),
            "variants": [],
            "confidence": 0.60,  # 规则回退置信度较低
            "content_type": "knowledge",
            "category": best.get("category", ""),
        }

    def batch_distill(
        self,
        entries: List[Dict],
        include_knowledge_base: bool = True,
        min_group_size: int = 2,
        max_workers: int = 5,
        on_progress=None,
    ) -> Tuple[List[Dict], Dict]:
        """
        批量知识蒸馏入口

        :param entries: 原始 RAG 条目列表
        :param include_knowledge_base: 是否合并手写知识库
        :param min_group_size: 最小分组大小（少于此数的组跳过）
        :param max_workers: 并发线程数
        :param on_progress: 进度回调 (completed, total)
        :return: (distilled_entries, stats)
        """
        stats = {
            "input": len(entries),
            "groups": 0,
            "distilled": 0,
            "skipped_small": 0,
            "failed": 0,
            "manual_entries": 0,
            "output": 0,
        }

        # Step 1: 按 intent 分组
        groups = group_by_intent(entries)
        stats["groups"] = len(groups)
        logger.info(f"[Distiller] 输入 {len(entries)} 条, 分为 {len(groups)} 组")

        # 过滤太小的组
        valid_groups = {
            intent: items
            for intent, items in groups.items()
            if len(items) >= min_group_size
        }
        stats["skipped_small"] = len(groups) - len(valid_groups)

        # Step 2: 并发蒸馏
        distilled = []
        completed_count = 0
        lock = threading.Lock()

        def _distill_one(intent_items):
            intent, items = intent_items
            return intent, self.distill_group(intent, items)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_distill_one, (intent, items)): intent
                for intent, items in valid_groups.items()
            }

            for future in as_completed(futures):
                intent, result = future.result()

                with lock:
                    completed_count += 1
                    if result:
                        distilled.append(result)
                        stats["distilled"] += 1
                    else:
                        stats["failed"] += 1

                    if on_progress:
                        on_progress(completed_count, len(valid_groups))

        logger.info(
            f"[Distiller] 蒸馏完成: 成功={stats['distilled']}, "
            f"失败={stats['failed']}, 跳过小组={stats['skipped_small']}"
        )

        # Step 3: 合并手写知识库
        if include_knowledge_base:
            knowledge_base = load_knowledge_base()
            stats["manual_entries"] = len(knowledge_base)
            merged = merge_with_knowledge_base(distilled, knowledge_base)
        else:
            merged = distilled

        stats["output"] = len(merged)

        return merged, stats


def flatten_for_volcano(entries: List[Dict]) -> List[Dict]:
    """
    将蒸馏结果展开为火山引擎兼容格式（question, answer 两列）

    每个 variant 独立一行，answer 重复。

    :param entries: 蒸馏后的知识条目列表
    :return: 展开后的 [{question, answer}] 列表
    """
    rows = []
    for entry in entries:
        q = entry.get("question", "").strip()
        a = entry.get("answer", "").strip()
        if not q or not a:
            continue

        # 主问题
        rows.append({"question": q, "answer": a})

        # 变体展开
        for v in entry.get("variants", []):
            v = v.strip()
            if v and v != q:
                rows.append({"question": v, "answer": a})

    return rows
