import os
import sqlite3
import sys
import tempfile
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.models.chat import Base, RawChat
from app.services.etl import MIN_TIMESTAMP, WeChatETL


class EtlIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self._create_msg_db()

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(bind=engine)
        self.db = self.SessionLocal()

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def _create_msg_db(self):
        multi_dir = os.path.join(self.temp_dir.name, "Multi")
        os.makedirs(multi_dir, exist_ok=True)
        msg_db_path = os.path.join(multi_dir, "MSG0.db")
        conn = sqlite3.connect(msg_db_path)
        conn.execute(
            """
            CREATE TABLE MSG (
                localId INTEGER,
                StrTalker TEXT,
                StrContent TEXT,
                CreateTime INTEGER,
                Type INTEGER,
                SubType INTEGER,
                IsSender INTEGER,
                DisplayContent TEXT,
                BytesExtra BLOB,
                MsgSvrID INTEGER
            )
            """
        )
        conn.execute(
            """
            INSERT INTO MSG (
                localId, StrTalker, StrContent, CreateTime, Type,
                SubType, IsSender, DisplayContent, BytesExtra, MsgSvrID
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "wxid_test_user",
                "本科可以学吗",
                MIN_TIMESTAMP,
                1,
                0,
                0,
                None,
                None,
                123456789,
            ),
        )
        conn.commit()
        conn.close()

    def test_process_messages_skips_existing_source_message(self):
        etl = WeChatETL(db_base_path=self.temp_dir.name)

        first_import = etl.process_messages(self.db, 0)
        second_import = etl.process_messages(self.db, 0)
        total = self.db.query(RawChat).count()

        self.assertEqual(first_import, 1)
        self.assertEqual(second_import, 0)
        self.assertEqual(total, 1)

    def test_run_full_etl_rejects_invalid_source_before_clearing_existing_data(self):
        invalid_dir = tempfile.TemporaryDirectory()
        etl = WeChatETL(db_base_path=invalid_dir.name)
        self.db.add(
            RawChat(
                local_id=99,
                session_id="wxid_existing",
                content="existing",
                msg_type=1,
                is_sender=False,
                timestamp=MIN_TIMESTAMP,
                source_db="MSG0",
            )
        )
        self.db.commit()

        with self.assertRaisesRegex(ValueError, "缺少核心微信数据库文件"):
            etl.run_full_etl(self.db, clear_existing=True)

        self.assertEqual(self.db.query(RawChat).count(), 1)
        invalid_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
