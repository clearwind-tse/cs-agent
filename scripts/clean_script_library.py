# -*- coding: utf-8 -*-
"""
话术库深度清洗 v2

修复三个核心问题:
1. 去除时效性内容（周三开始上课、今天爆单了、年后直播等）
2. 多轮对话压缩 → 只保留与 question 直接相关的核心回答行
3. 过长 answer 截断到关键信息

用法:
    python scripts/clean_script_library.py rag_script_library.csv -o rag_script_library_v2.csv
"""
import csv
import re
import argparse
from typing import List, Dict


# ==================== 时效性行模式 ====================
EPHEMERAL_PATTERNS = [
    # 具体时间
    r'周[一二三四五六日天]开始',
    r'周[一二三四五六日天].*上课',
    r'周[一二三四五六日天].*更新',
    r'周[一二三四五六日天].*直播',
    r'周[一二三四五六日天].*专场',
    r'周[一二三四五六日天].*会开',
    r'这周[一二三四五六日天]',
    r'下周[一二三四五六日天]',
    r'今天.*开始', r'明天.*开始',
    r'今天爆单', r'今天.*截止',
    r'今晚\d+点', r'今晚.*直播',
    r'昨天.*群里', r'昨晚.*直播',
    r'前天', r'前几天.*分享',
    r'刚才.*吃饭', r'刚才.*忙',
    r'我前几天.*分享',
    r'明天.*看一下', r'明天.*处理',
    # 时效性事件
    r'过了这周', r'不插班了',
    r'近期仅此一场', r'0点就没了',
    r'马上.*开班', r'马上.*开课',
    r'这一批.*刚开', r'这一批.*学生',
    r'1期还没毕业', r'2期.*招',
    r'年前.*毕业', r'年后.*直播',
    r'年后.*面试辅导', r'年后.*更新',
    r'上周出的offer',
    # 具体操作/当时情境
    r'我这会儿.*吃饭', r'这会儿.*忙',
    r'回家.*给你开课', r'给你改了个密码',
    r'你的账号', r'我给你.*密码',
    r'稍微晚点.*处理', r'晚点.*回复',
    r'我看你.*申请.*退款',
    r'你先进班', r'好了.*拉群',
    r'我先去忙', r'消息太多',
    r'现在视频是加密的.*流不出去',
    r'先给你下掉',
]

# 追问/销售动作行（不是知识）
SALES_ACTION_PATTERNS = [
    r'^啥时候来报道',
    r'^你估计要\d+个月',
    r'^你一天大概能学多久',
    r'^还在上班是吧',
    r'^跟你量身定制',
    r'^进一步深化友谊',
    r'^有点像同行.*打听',
    r'^你有点像同行',
    r'^忙死\s*都来了',
    r'^嗯啥时候来',
    r'^老朋友\d+折',
    r'^进一步深化',
    r'^把具体.*我给你梳理',
    r'^把.*情况.*介绍',
    r'^你先看.*到时候再说',
    r'^赶紧.*好了',
    r'^你随时约我',
    r'^干了半年.*是吗',
    r'^毕业这几年.*关键',
    r'^你啥也不知道',
    r'^跟你聊没意义',
    r'^你搜过岗位吗',
    r'^你对.*一无所知',
    r'^我建议你先搜',
    r'^看我朋友圈',
    r'^看下我朋友圈',
    r'^待会儿我会发朋友圈',
    r'^顺便给你们解答',
    r'^先发你大纲',
    r'^你今年不看.*明年更不会看',
]

# 闲聊/无信息行
CHITCHAT_PATTERNS = [
    r'^哈哈', r'^嗯嗯', r'^对的$', r'^是的$',
    r'^好的$', r'^ok$', r'^嗯$', r'^哦$',
    r'^没事', r'^行$', r'^可以$',
    r'^牛$', r'^厉害$', r'^加油$',
]


def clean_answer_lines_v2(answer: str, question: str) -> str:
    """
    深度清洗 answer 每一行:
    1. 删除时效性行
    2. 删除销售动作行
    3. 删除闲聊行
    4. 保留与问题相关的核心信息行
    """
    lines = answer.split('\n')
    clean_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # 跳过极短行（<=3字且无数字/字母）
        if len(stripped) <= 3 and not re.search(r'[\d\w]', stripped):
            continue

        # 跳过时效性行
        if any(re.search(p, stripped, re.IGNORECASE) for p in EPHEMERAL_PATTERNS):
            continue

        # 跳过销售动作行
        if any(re.match(p, stripped, re.IGNORECASE) for p in SALES_ACTION_PATTERNS):
            continue

        # 跳过闲聊行
        if any(re.match(p, stripped, re.IGNORECASE) for p in CHITCHAT_PATTERNS):
            continue

        clean_lines.append(stripped)

    return '\n'.join(clean_lines)


def truncate_answer(answer: str, max_lines: int = 6, max_chars: int = 250) -> str:
    """
    截断过长 answer:
    - 最多保留 max_lines 行
    - 最多保留 max_chars 字符
    - 优先保留前面的行（通常信息密度更高）
    """
    lines = [l.strip() for l in answer.split('\n') if l.strip()]

    # 行数截断
    if len(lines) > max_lines:
        lines = lines[:max_lines]

    # 字符数截断
    result = '\n'.join(lines)
    if len(result) > max_chars:
        # 逐行累加，超出时截断
        kept = []
        total = 0
        for line in lines:
            if total + len(line) > max_chars:
                break
            kept.append(line)
            total += len(line)
        result = '\n'.join(kept) if kept else lines[0][:max_chars]

    return result


def merge_short_lines_v2(text: str) -> str:
    """合并碎片短行"""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if len(lines) <= 1:
        return text.strip()

    merged = []
    buf = ''
    for line in lines:
        if re.match(r'^(\d+[\.\、]|\-\s)', line):
            if buf:
                merged.append(buf)
                buf = ''
            merged.append(line)
        elif len(line) < 12:
            buf = (buf + ' ' + line).strip() if buf else line
            if len(buf) > 50:
                merged.append(buf)
                buf = ''
        else:
            if buf:
                merged.append(buf)
                buf = ''
            merged.append(line)
    if buf:
        merged.append(buf)

    return '\n'.join(merged)


def clean_script_entry(row: Dict) -> Dict:
    """清洗单条话术记录"""
    result = dict(row)
    question = row.get('question', '')
    answer = row.get('answer', '')

    # 1. 逐行清洗
    answer = clean_answer_lines_v2(answer, question)

    # 2. 合并碎片
    answer = merge_short_lines_v2(answer)

    # 3. 截断过长
    answer = truncate_answer(answer)

    # 4. 清理空白
    answer = re.sub(r'\n\s*\n', '\n', answer).strip()

    result['answer'] = answer
    return result


def main():
    parser = argparse.ArgumentParser(description='话术库深度清洗 v2')
    parser.add_argument('input', help='输入 CSV')
    parser.add_argument('-o', '--output', default=None, help='输出 CSV')
    args = parser.parse_args()

    if args.output is None:
        import os
        base = os.path.splitext(args.input)[0]
        args.output = f"{base}_v2.csv"

    with open(args.input, 'r', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))

    print(f"输入: {len(rows)} 条")

    stats = {'removed_empty': 0, 'removed_short': 0}
    cleaned = []

    for row in rows:
        result = clean_script_entry(row)
        answer = result.get('answer', '').strip()

        if not answer:
            stats['removed_empty'] += 1
            continue
        if len(answer) < 20:
            stats['removed_short'] += 1
            continue

        cleaned.append(result)

    print(f"  清洗后为空: {stats['removed_empty']}")
    print(f"  过短(<20字): {stats['removed_short']}")
    print(f"输出: {len(cleaned)} 条 → {args.output}")

    # 写出
    fieldnames = ['question', 'answer', 'category', 'intent', 'tags', 'source', 'confidence', 'content_type']
    with open(args.output, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(cleaned)

    # 统计
    print()
    a_lens = [len(r['answer']) for r in cleaned]
    line_counts = [len(r['answer'].split('\n')) for r in cleaned]
    print(f"Answer长度: min={min(a_lens)}, max={max(a_lens)}, avg={sum(a_lens)/len(a_lens):.0f}")
    print(f"Answer行数: min={min(line_counts)}, max={max(line_counts)}, avg={sum(line_counts)/len(line_counts):.1f}")

    # 时效性残留检查
    time_count = sum(1 for r in cleaned
                     if any(re.search(p, r['answer']) for p in EPHEMERAL_PATTERNS))
    print(f"时效性残留: {time_count}")

    # 多轮压缩检查
    multi = sum(1 for r in cleaned if len(r['answer'].split('\n')) > 5)
    print(f"answer > 5行: {multi}")

    # 生成火山CSV
    volcano_path = args.output.replace('.csv', '_volcano.csv')
    with open(volcano_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['question', 'answer'])
        writer.writeheader()
        for row in cleaned:
            writer.writerow({'question': row['question'], 'answer': row['answer']})
    print(f"\n火山格式: {volcano_path}")


if __name__ == '__main__':
    main()
