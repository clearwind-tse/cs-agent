#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
训练数据清洗脚本
用于修复违反系统提示词规则的训练数据
"""
import json
import re
from typing import List, Dict, Any
from pathlib import Path


class TrainingDataCleaner:
    """训练数据清洗器"""

    def __init__(self):
        # 价格相关敏感词（违反硬性红线）
        self.price_keywords = [
            r'改价', r'优惠', r'折扣', r'便宜', r'多少钱', r'价格',
            r'\d+元', r'\d+块', r'\d+k', r'\d+w', r'分期', r'付款'
        ]

        # 标准回复模板（符合硬性红线）
        self.price_response = "价格这块懂王Ai经常有活动\n我得先看你合不合适带\n合适的话我推个教务老师给你\n你找他领最新优惠"

        # 禁用标点符号
        self.forbidden_punctuation = ['。', '，', '！', '？', '、', '；', '：', '"', '"', ''', ''']

        self.stats = {
            'total': 0,
            'price_violations': 0,
            'punctuation_violations': 0,
            'length_violations': 0,
            'cleaned': 0
        }

    def check_price_violation(self, text: str) -> bool:
        """检查是否违反价格红线"""
        for pattern in self.price_keywords:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    def clean_punctuation(self, text: str) -> str:
        """移除禁用标点符号"""
        cleaned = text
        for punct in self.forbidden_punctuation:
            cleaned = cleaned.replace(punct, '')
        return cleaned

    def split_long_lines(self, text: str, max_length: int = 15) -> str:
        """将超长行拆分为多行"""
        lines = text.split('\n')
        result = []

        for line in lines:
            if len(line) <= max_length:
                result.append(line)
            else:
                # 简单拆分：每15字一行
                words = list(line)
                chunks = [words[i:i+max_length] for i in range(0, len(words), max_length)]
                result.extend([''.join(chunk) for chunk in chunks])

        return '\n'.join(result)

    def clean_conversation(self, conv: Dict[str, str]) -> Dict[str, str]:
        """清洗单条对话"""
        if conv['from'] != 'gpt':
            return conv

        text = conv['value']
        original_text = text
        modified = False

        # 1. 检查价格违规
        if self.check_price_violation(text):
            self.stats['price_violations'] += 1
            # 如果是关于价格的回复，替换为标准模板
            text = self.price_response
            modified = True

        # 2. 移除标点符号
        cleaned_text = self.clean_punctuation(text)
        if cleaned_text != text:
            self.stats['punctuation_violations'] += 1
            text = cleaned_text
            modified = True

        # 3. 拆分超长行
        lines = text.split('\n')
        if any(len(line) > 15 for line in lines):
            self.stats['length_violations'] += 1
            text = self.split_long_lines(text)
            modified = True

        if modified:
            self.stats['cleaned'] += 1
            return {'from': conv['from'], 'value': text}

        return conv

    def clean_example(self, example: Dict[str, Any]) -> Dict[str, Any]:
        """清洗单个训练样本"""
        self.stats['total'] += 1

        cleaned_conversations = []
        for conv in example['conversations']:
            cleaned_conversations.append(self.clean_conversation(conv))

        return {
            **example,
            'conversations': cleaned_conversations
        }

    def clean_file(self, input_path: str, output_path: str = None):
        """清洗训练数据文件"""
        input_file = Path(input_path)

        if not input_file.exists():
            raise FileNotFoundError(f"文件不存在: {input_path}")

        # 读取数据
        print(f"📖 读取文件: {input_path}")
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        print(f"📊 总样本数: {len(data)}")

        # 清洗数据
        print("🧹 开始清洗...")
        cleaned_data = [self.clean_example(example) for example in data]

        # 输出路径
        if output_path is None:
            output_path = input_file.parent / f"{input_file.stem}_cleaned{input_file.suffix}"

        # 保存清洗后的数据
        print(f"💾 保存到: {output_path}")
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(cleaned_data, f, ensure_ascii=False, indent=2)

        # 打印统计信息
        self.print_stats()

        return str(output_path)

    def print_stats(self):
        """打印清洗统计"""
        print("\n" + "="*50)
        print("📊 清洗统计报告")
        print("="*50)
        print(f"总样本数:           {self.stats['total']}")
        print(f"价格违规修复:       {self.stats['price_violations']}")
        print(f"标点符号移除:       {self.stats['punctuation_violations']}")
        print(f"超长行拆分:         {self.stats['length_violations']}")
        print(f"总修改对话数:       {self.stats['cleaned']}")
        print("="*50)


def main():
    """主函数"""
    import sys

    if len(sys.argv) < 2:
        print("用法: python clean_training_data.py <input_file> [output_file]")
        print("示例: python clean_training_data.py labeled_training_sharegpt_145examples.json")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    cleaner = TrainingDataCleaner()
    try:
        output_path = cleaner.clean_file(input_file, output_file)
        print(f"\n✅ 清洗完成！输出文件: {output_path}")
    except Exception as e:
        print(f"\n❌ 清洗失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
