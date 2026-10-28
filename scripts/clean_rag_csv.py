# -*- coding: utf-8 -*-
"""
RAG 知识库 CSV 后处理清洗脚本

用法:
    python scripts/clean_rag_csv.py rag_llm_rewritten_20260413_1200.csv -o rag_cleaned.csv

核心原则: 保留说话风格（口语化、直接、犀利），修复结构性问题
"""
import csv
import re
import sys
import argparse
from collections import Counter
from typing import List, Dict, Tuple


# ==================== 配置 ====================

# 1. 噪音 question 黑名单（整条删除）
NOISE_QUESTION_KEYWORDS = [
    '新装宽带', 'ai创业粉', '创业粉',
]

# 噪音 question 精确匹配（整条删除）
NOISE_QUESTION_EXACT = [
    '要流水。半年的',
]

# 2. 微信表情模式
WECHAT_EMOJI_PATTERN = re.compile(r'\[[^\]]{1,8}\]')

# 已知微信表情列表（只删除这些，防止误删有意义的方括号内容）
KNOWN_WECHAT_EMOJIS = {
    '[捂脸]', '[破涕为笑]', '[坏笑]', '[旺柴]', '[呲牙]', '[害羞]',
    '[可怜]', '[苦涩]', '[流泪]', '[撇嘴]', '[社会社会]', '[强]',
    '[抱拳]', '[OK]', '[嘿哈]', '[机智]', '[加油]', '[微笑]',
    '[玫瑰]', '[拥抱]', '[握手]', '[鼓掌]', '[比心]', '[爱心]',
    '[太阳]', '[月亮]', '[咖啡]', '[蛋糕]', '[啤酒]', '[礼物]',
    '[烟花]', '[庆祝]', '[红包]', '[發]', '[福]', '[转圈]',
    '[跳跳]', '[发抖]', '[让我看看]', '[叹气]', '[裂开]',
    '[翻白眼]', '[666]', '[合十]', '[尬笑]', '[飘落叶]',
    '[若干]',  # 这是脱敏残留
}

# 断裂微信表情模式（换行导致方括号不闭合）
BROKEN_EMOJI_PATTERN = re.compile(r'\[(捂脸|可怜|破涕为笑|坏笑|旺柴|呲牙|害羞|苦涩|流泪|撇嘴|强|玫瑰|微笑|尬笑)\s*$', re.MULTILINE)

# 3. 固定话术模板特征（用于检测重复）
COURSE_INTRO_SIGNATURE = '你到手会有一个加密播放器'

# 精简版课程介绍（保留风格）
COURSE_INTRO_SHORT = """加密视频+直播答疑+班级群
按我规划的顺序学 不懂群里问
学差不多了约我模拟面试"""

# 4. 不当用语（按行删除，不删整条）
PROFANITY_PATTERNS = [
    r'Tmd|tmd|TMD',
    r'傻逼|sb|SB',
    r'尼玛',
    r'操你',
    r'你大专也配',
    r'你.*也配',
    r'废物',
    r'毒打',
    r'打回原形',
]

# 5. 追问行模式（删除这些行，它们是销售动作不是知识）
PROBING_LINE_PATTERNS = [
    r'^情况介绍我看',
    r'^你好\s*具体情况',
    r'^啥学历',
    r'^学历.*毕业',
    r'^之前是.*前端还是',
    r'^你是.*统招.*吗',
    r'^现在多少[kK]',
    r'^准备哪里找',
    r'^毕业多久了',
    r'^你现在多少',
    r'^有编程基础吗',
    r'^了?有编程基础吗',
    r'^对Ai.*了解吗',
    r'^了解Ai岗位嘛',
    r'^知道Ai是干啥',
    r'^了解这个岗位不',
    r'^你.*学历',
    r'^电话发我',
    r'^拉你进班',
    r'^你的飞书用户名',
    r'^飞书用户名',
    r'^消息太多',
    r'^这会来了',
    r'^我一个个来',
    r'^不好意思.*消息有点多',
    r'^最近我的消息确实有点多',
    r'^可以了\s*加好了',
]

# 6. 直播引流/时效性行（删除这些行）
EPHEMERAL_LINE_PATTERNS = [
    r'今晚\d+点',
    r'今晚.*直播',
    r'今天.*截止',
    r'近期仅此一场',
    r'不见不散',
    r'^看我朋友圈',
    r'^看下我朋友圈',
    r'^点我头像看',
    r'朋友圈.*发',
    r'抖音.*直播',
    r'^同学们都很忙',
    r'^最近我的消息',
    r'^我邀请了.*同学',
    r'1期.*不招生了',
    r'优惠.*结束了',
    r'0点就没了',
]

# 7. 操作性行（报名/付款指引，全部删除——RAG知识库不需要操作指引）
OPERATIONAL_PATTERNS = [
    r'群公告.*文档.*权限',
    r'微信付款方式私聊',
    r'直接转我也可以',
    r'课件.*播放器.*在',
    r'把.*电话.*发',
    r'拉你进班',
    r'课件和播放器都在',
    r'文档权限申请',
    r'备注写微信名',
    r'直接转就好',
    r'直接转我',
    r'可以直接转我',
]

# 10. 行内追问短语（合并后残留在行内的追问片段）
INLINE_PROBING_PHRASES = [
    r'情况介绍我看[看下一]?',
    r'情况先介绍我看[看下一]?',
    r'你好\s*情况介绍我看[看下一]?',
    r'你好\s*具体情况介绍我看[看下一]?',
    r'具体情况介绍我看[看下一]?',
]

# 11. 操作性行内短语（合并后残留在行内的操作指引片段）
INLINE_OPERATIONAL_PHRASES = [
    r'群公告[的中]?权限[你]?可以先?申请[一下]*[然后]?',
    r'群公告权限申请[一下]*',
    r'[你所]?需要的?一切信息都在群公告[中]?[有]?',
    r'[你所]*需要的?任何资料全部在群公告',
    r'就在群公告置顶啊?',
    r'播放器和课件[都]?[看在]?群公告',
    r'播放器和课件都在里面',
    r'一切信息都在群公告',
    r'课件和播放器都在文档里面[的]?',
    r'看群公告',
]

# 8. Intent 标准化映射
INTENT_NORMALIZE = {
    '学员案例、成功经验': '学员案例',
    '课程内容咨询、价格咨询': '课程内容咨询',
    '课程内容咨询、学习方式咨询、就业前景咨询': '课程内容咨询',
    '就业前景咨询、转行可行性咨询、学历要求咨询': '就业前景咨询',
    '一般咨询': '课程内容咨询',
}

# 9. 与课程/AI完全无关的条目检测
UNRELATED_PATTERNS = [
    r'^请问是新装宽带',
    r'^ai创业粉$',
]


# ==================== 清洗函数 ====================

def is_noise_entry(row: Dict) -> bool:
    """判断是否为噪音条目（整条删除）"""
    q = row.get('question', '')

    # 精确匹配
    if q.strip() in NOISE_QUESTION_EXACT:
        return True

    # 关键词匹配
    for kw in NOISE_QUESTION_KEYWORDS:
        if kw in q:
            return True

    # 完全无关的问答
    for pat in UNRELATED_PATTERNS:
        if re.match(pat, q.strip()):
            return True

    return False


def remove_wechat_emojis(text: str) -> str:
    """删除微信表情标记（包括断裂的）"""
    # 先处理断裂的表情（行末的 [可怜 等）
    result = BROKEN_EMOJI_PATTERN.sub('', text)

    # 再处理完整的表情
    def _replace(m):
        if m.group(0) in KNOWN_WECHAT_EMOJIS:
            return ''
        return m.group(0)  # 不认识的保留

    result = WECHAT_EMOJI_PATTERN.sub(_replace, result)
    # 清理多余空格
    result = re.sub(r'  +', ' ', result)
    return result.strip()


def has_course_intro_template(answer: str) -> bool:
    """检查是否包含固定课程介绍话术"""
    return COURSE_INTRO_SIGNATURE in answer


def clean_answer_lines(answer: str) -> str:
    """
    清洗 answer 的每一行:
    - 删除追问行
    - 删除引流行
    - 删除不当用语行
    - 删除操作性指引行（去重后只保留一处）
    """
    lines = answer.split('\n')
    clean_lines = []
    kept_operational = False  # 操作性行只保留一次

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # 跳过追问行
        if any(re.match(p, stripped, re.IGNORECASE) for p in PROBING_LINE_PATTERNS):
            continue

        # 跳过引流行
        if any(re.search(p, stripped, re.IGNORECASE) for p in EPHEMERAL_LINE_PATTERNS):
            continue

        # 跳过不当用语行
        if any(re.search(p, stripped, re.IGNORECASE) for p in PROFANITY_PATTERNS):
            continue

        # 操作性行全部删除（RAG知识库不需要操作指引）
        if any(re.search(p, stripped) for p in OPERATIONAL_PATTERNS):
            continue

        # 跳过极短无信息行（<=2字且没数字）
        if len(stripped) <= 2 and not re.search(r'\d', stripped):
            continue

        clean_lines.append(stripped)

    return '\n'.join(clean_lines)


def merge_short_lines(text: str, max_short: int = 15) -> str:
    """
    合并碎片化短行为连贯段落

    策略:
    - 相邻的短行（<max_short字符）合并为一行，用空格连接
    - 长行（>=max_short）独立保留
    - 遇到列表标记（1. 2. 3. -）保留换行
    """
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if len(lines) <= 1:
        return text.strip()

    merged = []
    buffer = ''

    for line in lines:
        # 列表标记，强制换行
        if re.match(r'^(\d+[\.\、]|\-\s)', line):
            if buffer:
                merged.append(buffer)
                buffer = ''
            merged.append(line)
            continue

        # 短行 → 合并到 buffer
        if len(line) < max_short:
            if buffer:
                # 如果 buffer 已经很长了，先输出
                if len(buffer) + len(line) > 60:
                    merged.append(buffer)
                    buffer = line
                else:
                    buffer += ' ' + line
            else:
                buffer = line
        else:
            # 长行 → 先输出 buffer，再输出当前行
            if buffer:
                merged.append(buffer)
                buffer = ''
            merged.append(line)

    if buffer:
        merged.append(buffer)

    return '\n'.join(merged)


def strip_inline_probing(text: str) -> str:
    """
    剥离行内追问和操作性短语（合并短行后残留在行内的片段）
    例如: "情况介绍我看下 成人大专肯定比统招..." → "成人大专肯定比统招..."
    例如: "一切信息都在群公告 我看你申请了退款" → "我看你申请了退款"
    """
    for phrase in INLINE_PROBING_PHRASES:
        text = re.sub(phrase + r'\s*', '', text)
    for phrase in INLINE_OPERATIONAL_PHRASES:
        text = re.sub(phrase + r'\s*', '', text)
    # 清理行首空格
    text = re.sub(r'^\s+', '', text, flags=re.MULTILINE)
    # 删除变空的行
    text = '\n'.join(l for l in text.split('\n') if l.strip())
    return text.strip()


def clean_single_entry(row: Dict) -> Dict:
    """清洗单条记录"""
    result = dict(row)

    # 1. 清洗 answer
    answer = result.get('answer', '')

    # 删除微信表情
    answer = remove_wechat_emojis(answer)

    # 逐行清洗（删追问/引流/脏话/操作行）
    answer = clean_answer_lines(answer)

    # 合并碎片化短行
    answer = merge_short_lines(answer)

    # 剥离行内追问短语
    answer = strip_inline_probing(answer)

    # 清理多余空行
    answer = re.sub(r'\n\s*\n', '\n', answer).strip()

    result['answer'] = answer

    # 2. 清洗 question
    question = result.get('question', '')
    question = remove_wechat_emojis(question)
    result['question'] = question.strip()

    # 3. 标准化 intent
    intent = result.get('intent', '')
    if intent in INTENT_NORMALIZE:
        result['intent'] = INTENT_NORMALIZE[intent]

    return result


def deduplicate_course_intro(rows: List[Dict]) -> List[Dict]:
    """
    对包含固定课程介绍话术的条目去重:
    - 保留 1 条最佳的（question 最完整的）
    - 其余替换为精简版
    """
    intro_indices = []
    non_intro = []

    for i, row in enumerate(rows):
        if has_course_intro_template(row.get('answer', '')):
            intro_indices.append(i)
        else:
            non_intro.append(row)

    if len(intro_indices) <= 1:
        return rows

    # 找最佳条目（question 最长且 confidence 最高的）
    best_idx = max(intro_indices, key=lambda i: (
        len(rows[i].get('question', '')),
        float(rows[i].get('confidence', 0))
    ))

    result = []
    replaced_count = 0
    for i, row in enumerate(rows):
        if i in intro_indices:
            if i == best_idx:
                # 保留完整版
                result.append(row)
            else:
                # 替换为精简版
                new_row = dict(row)
                new_row['answer'] = COURSE_INTRO_SHORT
                result.append(new_row)
                replaced_count += 1
        else:
            result.append(row)

    print(f"  [去重] 固定课程介绍: 保留1条完整版, {replaced_count}条替换为精简版")
    return result


# ==================== 主流程 ====================

def clean_csv(input_path: str, output_path: str, min_confidence: float = 0.5):
    """主清洗流程"""

    # 读取
    with open(input_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    total_input = len(rows)
    print(f"读取 {total_input} 条记录")

    stats = {
        'input': total_input,
        'noise_removed': 0,
        'low_conf_removed': 0,
        'short_answer_removed': 0,
        'output': 0,
    }

    # Step 1: 删除噪音数据
    filtered = []
    for row in rows:
        if is_noise_entry(row):
            stats['noise_removed'] += 1
        else:
            filtered.append(row)
    print(f"  [噪音] 删除 {stats['noise_removed']} 条")

    # Step 2: 过滤低 confidence
    conf_filtered = []
    for row in filtered:
        try:
            conf = float(row.get('confidence', 0))
        except (ValueError, TypeError):
            conf = 0
        if conf < min_confidence:
            stats['low_conf_removed'] += 1
        else:
            conf_filtered.append(row)
    filtered = conf_filtered
    print(f"  [置信度] 过滤 confidence < {min_confidence}: 删除 {stats['low_conf_removed']} 条")

    # Step 3: 去重固定话术
    filtered = deduplicate_course_intro(filtered)

    # Step 4: 逐条清洗
    cleaned = []
    for row in filtered:
        clean_row = clean_single_entry(row)

        # 清洗后 answer 太短，跳过
        if len(clean_row.get('answer', '').strip()) < 10:
            stats['short_answer_removed'] += 1
            continue

        cleaned.append(clean_row)
    print(f"  [过短] answer < 10字: 删除 {stats['short_answer_removed']} 条")

    stats['output'] = len(cleaned)
    print(f"\n清洗完成: {stats['input']} → {stats['output']} 条 (删除 {stats['input'] - stats['output']} 条)")

    # 写出
    fieldnames = ['question', 'answer', 'category', 'intent', 'tags', 'source', 'confidence', 'content_type']
    with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(cleaned)

    print(f"输出文件: {output_path}")

    # 清洗后统计
    print_post_stats(cleaned)

    return stats


def print_post_stats(rows: List[Dict]):
    """打印清洗后统计"""
    print(f"\n{'='*50}")
    print(f"清洗后数据统计")
    print(f"{'='*50}")

    # 微信表情检查
    emoji_count = sum(1 for r in rows
                      if any(e in r.get('answer', '') for e in KNOWN_WECHAT_EMOJIS))
    print(f"微信表情残留: {emoji_count} 条")

    # 固定话术检查
    intro_count = sum(1 for r in rows if COURSE_INTRO_SIGNATURE in r.get('answer', ''))
    print(f"固定课程介绍完整版: {intro_count} 条")

    # 碎片化检查（>3行且60%行<15字）
    fragment_count = 0
    for r in rows:
        lines = [l.strip() for l in r.get('answer', '').split('\n') if l.strip()]
        short_lines = sum(1 for l in lines if len(l) < 15)
        if len(lines) > 3 and short_lines / len(lines) > 0.6:
            fragment_count += 1
    print(f"碎片化格式: {fragment_count} 条 ({fragment_count/len(rows)*100:.1f}%)")

    # 不当用语检查
    profanity_count = sum(1 for r in rows
                          if any(re.search(p, r.get('answer', ''), re.IGNORECASE)
                                 for p in PROFANITY_PATTERNS))
    print(f"不当用语: {profanity_count} 条")

    # intent 分布
    intents = Counter(r.get('intent', '') for r in rows)
    print(f"\nIntent 分布:")
    for k, v in intents.most_common(15):
        print(f"  {k}: {v}")

    # answer 长度统计
    lens = [len(r.get('answer', '')) for r in rows]
    print(f"\nAnswer 长度: 最小={min(lens)}, 最大={max(lens)}, 平均={sum(lens)/len(lens):.0f}")


def main():
    parser = argparse.ArgumentParser(description='RAG 知识库 CSV 清洗工具')
    parser.add_argument('input', help='输入 CSV 文件路径')
    parser.add_argument('-o', '--output', default=None, help='输出 CSV 文件路径')
    parser.add_argument('--min-confidence', type=float, default=0.5,
                        help='最低置信度阈值 (默认 0.5)')

    args = parser.parse_args()

    if args.output is None:
        # 默认输出文件名
        import os
        base = os.path.splitext(args.input)[0]
        args.output = f"{base}_cleaned.csv"

    clean_csv(args.input, args.output, args.min_confidence)


if __name__ == '__main__':
    main()
