import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.services.schema_sync import (
    get_missing_material_columns,
    get_missing_raw_chat_columns,
    get_missing_student_columns,
)


class RawChatSchemaSyncTests(unittest.TestCase):
    def test_legacy_raw_chat_schema_requires_media_columns(self):
        existing_columns = {
            'id',
            'local_id',
            'session_id',
            'sender_wxid',
            'sender_name',
            'content',
            'msg_type',
            'is_sender',
            'timestamp',
            'display_content',
            'extra_data',
            'source_db',
            'created_at',
            'status',
            'clean_content',
            'auto_category',
            'auto_flags',
            'reviewed_by',
            'reviewed_at',
        }

        missing = get_missing_raw_chat_columns(existing_columns)

        self.assertEqual(
            missing,
            [
                ('msg_server_id', 'BIGINT'),
                ('voice_path', 'VARCHAR(300)'),
            ],
        )


class MaterialSchemaSyncTests(unittest.TestCase):
    def test_legacy_material_schema_requires_remark_and_binding_columns(self):
        existing_columns = {
            'id',
            'filename',
            'stored_name',
            'file_size',
            'file_type',
            'category',
            'title',
            'description',
            'tags',
            'uploaded_by',
            'download_count',
            'oss_key',
            'created_at',
        }

        missing = get_missing_material_columns(existing_columns)

        self.assertEqual(
            missing,
            [
                ('remark', 'VARCHAR(500)'),
                ('source_material_id', 'INTEGER'),
                ('is_pre_masked', 'BOOLEAN DEFAULT FALSE'),
                ('folder_id', 'INTEGER'),
            ],
        )


class StudentSchemaSyncTests(unittest.TestCase):
    def test_legacy_student_schema_requires_profile_and_report_columns(self):
        existing_columns = {
            'id',
            'name',
            'channel',
            'job_title',
            'pre_salary',
            'post_salary',
            'bday',
            'enroll_date',
            'graduation_date',
            'phone',
            'douyin_order',
            'class_name',
            'status',
            'created_at',
            'updated_at',
        }

        missing = get_missing_student_columns(existing_columns)

        self.assertEqual(
            missing,
            [
                ('city', 'VARCHAR(100)'),
                ('education', 'VARCHAR(50)'),
                ('graduation_cohort', 'VARCHAR(50)'),
                ('main_report_material_id', 'INTEGER'),
            ],
        )


if __name__ == '__main__':
    unittest.main()
