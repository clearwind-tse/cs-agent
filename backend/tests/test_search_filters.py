import os
import sys
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.models.chat import Base, RawChat, Session as ChatSession
from app.routers.search import search_messages, search_sessions


class SearchFilterTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(bind=engine)
        self.db = self.SessionLocal()

        self.db.add_all([
            ChatSession(
                session_id='wxid_private',
                display_name='学员小李',
                is_chatroom=False,
                last_message='本科可以学吗',
                last_time=1760000000,
                message_count=1,
            ),
            ChatSession(
                session_id='group123@chatroom',
                display_name='学习群',
                is_chatroom=True,
                last_message='本科可以学吗',
                last_time=1760000001,
                message_count=1,
            ),
        ])
        self.db.add_all([
            RawChat(
                local_id=1,
                session_id='wxid_private',
                sender_name='张三',
                content='本科可以学吗',
                msg_type=1,
                is_sender=False,
                timestamp=1760000000,
            ),
            RawChat(
                local_id=2,
                session_id='group123@chatroom',
                sender_name='学习群成员',
                content='本科可以学吗',
                msg_type=1,
                is_sender=False,
                timestamp=1760000001,
            ),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_search_messages_excludes_chatrooms_by_default(self):
        result = search_messages(q='本科', page=1, page_size=20, db=self.db)

        self.assertEqual(result.total, 1)
        self.assertEqual([item.session_id for item in result.items], ['wxid_private'])

    def test_search_messages_can_include_chatrooms_when_explicitly_enabled(self):
        result = search_messages(q='本科', page=1, page_size=20, exclude_chatroom=False, db=self.db)

        self.assertEqual(result.total, 2)

    def test_search_sessions_excludes_chatrooms_by_default(self):
        result = search_sessions(q='学', limit=10, db=self.db)

        self.assertEqual([item['session_id'] for item in result], ['wxid_private'])


if __name__ == '__main__':
    unittest.main()
