import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.services.staging_text import (
    dedupe_consecutive_lines,
    normalize_conversation_json,
    rebuild_cleaned_text,
)


class StagingTextTests(unittest.TestCase):
    def test_dedupe_consecutive_lines_removes_adjacent_duplicates_only(self):
        text = "你好 有课程课表吗\n你好 有课程课表吗\n我想了解下\n你好 有课程课表吗"

        normalized = dedupe_consecutive_lines(text)

        self.assertEqual(
            normalized,
            "你好 有课程课表吗\n我想了解下\n你好 有课程课表吗",
        )

    def test_normalize_conversation_json_dedupes_repeated_lines_inside_same_turn(self):
        turns = [
            {
                "role": "user",
                "sender_name": "香榭的落叶🍂",
                "content": "我是香榭的落叶🍂\n你好 有课程课表吗\n你好 有课程课表吗",
            },
            {
                "role": "assistant",
                "sender_name": "我",
                "content": "你好[旺柴]\n情况介绍我看一下，毕业多久了？什么学历",
            },
        ]

        normalized_turns = normalize_conversation_json(turns)
        cleaned_text = rebuild_cleaned_text(normalized_turns)

        self.assertEqual(
            normalized_turns[0]["content"],
            "我是香榭的落叶🍂\n你好 有课程课表吗",
        )
        self.assertEqual(
            cleaned_text,
            "香榭的落叶🍂: 我是香榭的落叶🍂\n你好 有课程课表吗\n我: 你好[旺柴]\n情况介绍我看一下，毕业多久了？什么学历",
        )


if __name__ == "__main__":
    unittest.main()
