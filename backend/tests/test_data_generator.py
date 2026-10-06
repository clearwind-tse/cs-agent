import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.services.data_generator import DataGenerator


class _FakeInvalidJsonResponse:
    def __init__(self):
        self.choices = [type("Choice", (), {"message": type("Message", (), {"content": "not-json"})()})()]


class _FakeInvalidJsonCompletions:
    def create(self, **kwargs):
        return _FakeInvalidJsonResponse()


class _FakeInvalidJsonClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": _FakeInvalidJsonCompletions()})()


class DataGeneratorTests(unittest.TestCase):
    def test_generator_falls_back_to_builtin_examples_when_external_file_missing(self):
        generator = DataGenerator()
        generator.real_examples = []

        examples = generator._get_few_shot_examples("course", count=1)

        self.assertGreaterEqual(len(examples), 1)
        self.assertEqual(examples[0][0]["role"], "user")

    def test_generate_batch_records_failure_reason_for_rejected_items(self):
        generator = DataGenerator()
        generator.client = _FakeInvalidJsonClient()
        generator.model = "fake-model"
        generator.real_examples = []

        progress = generator.generate_batch(target_count=1, categories=["course"])

        self.assertGreater(progress.total, 0)
        self.assertEqual(progress.failed, progress.total)
        self.assertGreaterEqual(len(progress.errors), 1)


if __name__ == "__main__":
    unittest.main()
