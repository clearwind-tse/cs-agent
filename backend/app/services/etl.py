# -*- coding: utf-8 -*-
"""
ETL 数据清洗服务
将微信 SQLite 数据导入 PostgreSQL
"""
import sqlite3
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session as DBSession

from app.config import get_settings
from app.models.chat import Contact, Session, RawChat

settings = get_settings()

# 时间过滤：只导入 2025年10月 及以后的数据
# 2025-10-01 00:00:00 北京时间 的 Unix 时间戳
MIN_TIMESTAMP = 1759248000  # 2025-10-01 00:00:00 CST (秒级)


class WeChatETL:
    """微信数据 ETL 处理器"""
    
    def __init__(self, db_base_path: str = None):
        self.db_base_path = db_base_path or settings.wechat_db_path
        self.voice_base_path = settings.voice_file_path
        self.user_map: Dict[str, str] = {}  # wxid -> display_name
        self.chatroom_members: Dict[str, Dict[str, str]] = {}  # chatroom_id -> {wxid: name}
        self.voice_files: set = set()  # 语音文件名集合（不含后缀）
    
    def load_voice_files(self):
        """预加载语音文件列表，用于快速映射"""
        abs_path = os.path.abspath(self.voice_base_path)
        print(f"[INFO] 语音目录配置: {self.voice_base_path} (绝对路径: {abs_path})")
        
        if not os.path.exists(self.voice_base_path):
            print(f"[WARN] 语音文件目录不存在: {abs_path}")
            return
        
        for f in os.listdir(self.voice_base_path):
            if f.endswith('.mp3'):
                self.voice_files.add(f[:-4])  # 去掉 .mp3 后缀
        
        print(f"[INFO] 加载 {len(self.voice_files)} 个语音文件")
    
    def load_contacts(self) -> Dict[str, dict]:
        """
        加载通讯录
        返回: {wxid: {nickname, remark, alias, display_name, avatar_url, is_chatroom}}
        """
        contacts = {}
        micromsg_path = os.path.join(self.db_base_path, 'MicroMsg.db')
        
        if not os.path.exists(micromsg_path):
            print(f"[ERROR] MicroMsg.db not found: {micromsg_path}")
            return contacts
        
        conn = sqlite3.connect(f'file:{micromsg_path}?immutable=1', uri=True)
        
        # 加载联系人
        query = """
            SELECT UserName, Alias, NickName, Remark, SmallHeadImgUrl
            FROM Contact 
            WHERE UserName IS NOT NULL
        """
        cursor = conn.execute(query)
        
        for row in cursor:
            wxid, alias, nickname, remark, avatar = row
            is_chatroom = wxid.endswith('@chatroom') if wxid else False
            display_name = remark or nickname or alias or wxid
            
            contacts[wxid] = {
                'wxid': wxid,
                'alias': alias,
                'nickname': nickname,
                'remark': remark,
                'display_name': display_name,
                'avatar_url': avatar,
                'is_chatroom': is_chatroom
            }
            
            # 更新快速查找映射
            self.user_map[wxid] = display_name
        
        conn.close()
        print(f"[INFO] Loaded {len(contacts)} contacts")
        return contacts
    
    def load_chatroom_members(self) -> Dict[str, Dict[str, str]]:
        """
        加载群成员信息
        返回: {chatroom_id: {wxid: display_name}}
        """
        chatroom_path = os.path.join(self.db_base_path, 'ChatRoomUser.db')
        
        if not os.path.exists(chatroom_path):
            print(f"[WARN] ChatRoomUser.db not found: {chatroom_path}")
            return {}
        
        conn = sqlite3.connect(f'file:{chatroom_path}?immutable=1', uri=True)
        
        try:
            # 尝试查询群成员表
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [t[0] for t in cursor.fetchall()]
            print(f"[INFO] ChatRoomUser.db tables: {tables}")
            
            # 根据实际表结构加载数据
            if 'ChatRoomUser' in tables:
                query = "SELECT chatroomName, userName, displayName FROM ChatRoomUser"
                cursor = conn.execute(query)
                for row in cursor:
                    chatroom_id, wxid, name = row
                    if chatroom_id not in self.chatroom_members:
                        self.chatroom_members[chatroom_id] = {}
                    # 优先使用通讯录中的名称
                    display_name = self.user_map.get(wxid, name or wxid)
                    self.chatroom_members[chatroom_id][wxid] = display_name
        except Exception as e:
            print(f"[WARN] Failed to load chatroom members: {e}")
        
        conn.close()
        return self.chatroom_members
    
    def parse_group_sender(self, content: str, bytes_extra: bytes, chatroom_id: str) -> Tuple[str, str, str]:
        """
        解析群消息的实际发送者
        返回: (sender_wxid, sender_name, clean_content)
        """
        sender_wxid = None
        sender_name = None
        clean_content = content
        
        # 方法1: 从消息内容中解析 (格式: "wxid:\n实际内容")
        if content and ':\n' in content:
            parts = content.split(':\n', 1)
            if len(parts) == 2 and parts[0].startswith('wxid_'):
                sender_wxid = parts[0]
                clean_content = parts[1]
        
        # 方法2: 从 BytesExtra 中解析 (二进制数据)
        if bytes_extra and not sender_wxid:
            try:
                # BytesExtra 中通常包含发送者 wxid
                extra_str = bytes_extra.decode('utf-8', errors='ignore')
                wxid_match = re.search(r'(wxid_[a-zA-Z0-9]+)', extra_str)
                if wxid_match:
                    sender_wxid = wxid_match.group(1)
            except:
                pass
        
        # 获取发送者名称
        if sender_wxid:
            # 优先从群成员中查找
            if chatroom_id in self.chatroom_members:
                sender_name = self.chatroom_members[chatroom_id].get(sender_wxid)
            # 其次从通讯录中查找
            if not sender_name:
                sender_name = self.user_map.get(sender_wxid, sender_wxid)
        
        return sender_wxid, sender_name, clean_content

    def validate_source_data(self):
        """
        校验微信源目录是否可用，避免在空目录上执行 clear_existing 后导入 0 条。
        """
        micromsg_path = os.path.join(self.db_base_path, "MicroMsg.db")
        multi_dir = os.path.join(self.db_base_path, "Multi")
        has_msg_db = any(
            os.path.exists(os.path.join(multi_dir, f"MSG{i}.db"))
            for i in range(6)
        )

        if os.path.exists(micromsg_path) and has_msg_db:
            return

        raise ValueError(
            f"缺少核心微信数据库文件，请检查数据源目录: {self.db_base_path}"
        )

    def save_message_batch(self, db_session: DBSession, source_db: str, batch: List[RawChat]) -> int:
        """
        批量写入消息，并按 source_db + local_id 去重，避免重复导入。
        """
        if not batch:
            return 0

        local_ids = list({chat.local_id for chat in batch if chat.local_id is not None})
        existing_local_ids = set()
        if local_ids:
            existing_local_ids = {
                local_id
                for (local_id,) in db_session.query(RawChat.local_id).filter(
                    RawChat.source_db == source_db,
                    RawChat.local_id.in_(local_ids),
                ).all()
            }

        deduped_batch = []
        pending_local_ids = set()
        for chat in batch:
            if chat.local_id is not None:
                if chat.local_id in existing_local_ids or chat.local_id in pending_local_ids:
                    continue
                pending_local_ids.add(chat.local_id)
            deduped_batch.append(chat)

        if not deduped_batch:
            return 0

        db_session.bulk_save_objects(deduped_batch)
        db_session.commit()
        return len(deduped_batch)
    
    def process_messages(self, db_session: DBSession, msg_db_index: int = 0) -> int:
        """
        处理单个 MSG 数据库的消息
        返回: 处理的消息数量
        """
        msg_path = os.path.join(self.db_base_path, 'Multi', f'MSG{msg_db_index}.db')
        
        if not os.path.exists(msg_path):
            print(f"[WARN] MSG{msg_db_index}.db not found")
            return 0
        
        conn = sqlite3.connect(f'file:{msg_path}?immutable=1', uri=True)
        source_db = f'MSG{msg_db_index}'
        
        # 查询消息，包含 MsgSvrID 用于关联语音等媒体文件
        query = """
            SELECT localId, StrTalker, StrContent, CreateTime, Type, 
                   SubType, IsSender, DisplayContent, BytesExtra, MsgSvrID
            FROM MSG 
            ORDER BY CreateTime
        """
        
        cursor = conn.execute(query)
        processed = 0
        voice_linked = 0
        batch = []
        batch_size = 1000
        
        for row in cursor:
            local_id, talker, content, timestamp, msg_type, sub_type, is_sender, display_content, bytes_extra, msg_svr_id = row
            
            if not talker:
                continue
            
            # 过滤 2025年10月 以前的数据
            if timestamp and timestamp < MIN_TIMESTAMP:
                continue
            
            is_chatroom = talker.endswith('@chatroom')
            sender_wxid = None
            sender_name = None
            clean_content = content
            
            # 处理群消息
            if is_chatroom and not is_sender:
                sender_wxid, sender_name, clean_content = self.parse_group_sender(
                    content, bytes_extra, talker
                )
            elif is_sender:
                sender_wxid = 'self'
                sender_name = '我'
            else:
                sender_wxid = talker
                sender_name = self.user_map.get(talker, talker)
            
            # 语音文件路径匹配
            voice_path = None
            if msg_type == 34 and msg_svr_id and self.voice_files:
                voice_key = str(msg_svr_id)
                if voice_key in self.voice_files:
                    voice_path = f"Voice/{voice_key}.mp3"
                    voice_linked += 1
            
            # 创建消息记录
            chat = RawChat(
                local_id=local_id,
                session_id=talker,
                sender_wxid=sender_wxid,
                sender_name=sender_name,
                content=clean_content,
                msg_type=msg_type,
                is_sender=bool(is_sender),
                timestamp=timestamp,
                display_content=display_content,
                source_db=source_db,
                msg_server_id=msg_svr_id,
                voice_path=voice_path
            )
            batch.append(chat)
            
            # 批量插入
            if len(batch) >= batch_size:
                processed += self.save_message_batch(db_session, source_db, batch)
                print(f"[INFO] {source_db}: Processed {processed} messages...")
                batch = []
        
        # 插入剩余数据
        if batch:
            processed += self.save_message_batch(db_session, source_db, batch)
        
        conn.close()
        print(f"[INFO] {source_db}: Total {processed} messages processed ({voice_linked} voice linked)")
        return processed
    
    def relink_voice_files(self, db_session: DBSession) -> int:
        """
        语音补链：扫描 Voice 目录，为 voice_path 为空的语音消息补充路径。
        用于 ETL 导入后自动修复因目录不可用而未匹配到的语音文件。
        """
        if not os.path.exists(self.voice_base_path):
            print(f"[WARN] 语音补链跳过：目录不存在 {os.path.abspath(self.voice_base_path)}")
            return 0
        
        # 加载语音文件名集合
        voice_keys = set()
        for f in os.listdir(self.voice_base_path):
            if f.endswith('.mp3'):
                voice_keys.add(f[:-4])
        
        if not voice_keys:
            print("[INFO] 语音补链跳过：目录为空")
            return 0
        
        # 查询 voice_path 为空的语音消息
        voice_messages = db_session.query(RawChat).filter(
            RawChat.msg_type == 34,
            (RawChat.voice_path == None) | (RawChat.voice_path == '')
        ).all()
        
        linked = 0
        for msg in voice_messages:
            if msg.msg_server_id and str(msg.msg_server_id) in voice_keys:
                msg.voice_path = f"Voice/{msg.msg_server_id}.mp3"
                linked += 1
        
        if linked > 0:
            db_session.commit()
        
        print(f"[INFO] 语音补链完成：{len(voice_keys)} 个文件，{len(voice_messages)} 条待补链，成功 {linked} 条")
        return linked
    
    def build_sessions(self, db_session: DBSession) -> int:
        """
        根据消息记录构建会话列表（UPSERT模式，已有则更新）
        """
        from sqlalchemy import func, desc
        
        # 统计每个会话的消息数量和最后一条消息
        query = db_session.query(
            RawChat.session_id,
            func.count(RawChat.id).label('count'),
            func.max(RawChat.timestamp).label('last_time')
        ).group_by(RawChat.session_id)
        
        sessions_created = 0
        for row in query:
            session_id, count, last_time = row
            
            # 获取最后一条消息
            last_msg = db_session.query(RawChat).filter(
                RawChat.session_id == session_id,
                RawChat.timestamp == last_time
            ).first()
            
            is_chatroom = session_id.endswith('@chatroom')
            display_name = self.user_map.get(session_id, session_id)
            
            # UPSERT：先查是否已存在
            existing = db_session.query(Session).filter(
                Session.session_id == session_id
            ).first()
            
            if existing:
                existing.display_name = display_name
                existing.is_chatroom = is_chatroom
                existing.last_message = last_msg.content[:100] if last_msg and last_msg.content else None
                existing.last_time = last_time
                existing.message_count = count
            else:
                session = Session(
                    session_id=session_id,
                    display_name=display_name,
                    is_chatroom=is_chatroom,
                    last_message=last_msg.content[:100] if last_msg and last_msg.content else None,
                    last_time=last_time,
                    message_count=count
                )
                db_session.add(session)
            sessions_created += 1
        
        db_session.commit()
        print(f"[INFO] Created/Updated {sessions_created} sessions")
        return sessions_created
    
    def save_contacts(self, db_session: DBSession, contacts: Dict[str, dict]) -> int:
        """
        保存联系人到数据库（使用 merge 避免唯一约束冲突）
        """
        saved = 0
        batch = []
        for wxid, info in contacts.items():
            # 检查是否已存在
            existing = db_session.query(Contact).filter(Contact.wxid == wxid).first()
            if existing:
                # 更新已有记录
                existing.alias = info.get('alias')
                existing.nickname = info.get('nickname')
                existing.remark = info.get('remark')
                existing.display_name = info.get('display_name')
                existing.avatar_url = info.get('avatar_url')
                existing.is_chatroom = info.get('is_chatroom', False)
            else:
                contact = Contact(
                    wxid=wxid,
                    alias=info.get('alias'),
                    nickname=info.get('nickname'),
                    remark=info.get('remark'),
                    display_name=info.get('display_name'),
                    avatar_url=info.get('avatar_url'),
                    is_chatroom=info.get('is_chatroom', False)
                )
                db_session.add(contact)
            saved += 1
        
        db_session.commit()
        print(f"[INFO] Saved/Updated {saved} contacts")
        return saved
    
    def clear_existing_data(self, db_session: DBSession):
        """
        清除现有的 ETL 导入数据（用于重新导入）
        注意：不清除 staging_conversations 和 labeled_conversations（人工标注数据）
        """
        from app.models.chat import Session
        
        print("[INFO] 开始清除旧数据...")
        
        # 清除原始聊天记录
        deleted_raw = db_session.query(RawChat).delete()
        print(f"[INFO]   清除 raw_chats: {deleted_raw} 条")
        
        # 清除会话记录
        deleted_sessions = db_session.query(Session).delete()
        print(f"[INFO]   清除 sessions: {deleted_sessions} 条")
        
        # 清除联系人（联系人会在后面重新导入）
        deleted_contacts = db_session.query(Contact).delete()
        print(f"[INFO]   清除 contacts: {deleted_contacts} 条")
        
        db_session.commit()
        print(f"[INFO] 旧数据清除完成，共删除 {deleted_raw + deleted_sessions + deleted_contacts} 条记录")
        
        return {
            'raw_chats': deleted_raw,
            'sessions': deleted_sessions,
            'contacts': deleted_contacts
        }
    
    def run_full_etl(self, db_session: DBSession, clear_existing: bool = False) -> dict:
        """
        运行完整的 ETL 流程
        
        Args:
            db_session: 数据库会话
            clear_existing: 是否先清除现有数据再导入（用于数据源更换/更新）
        """
        stats = {
            'contacts': 0,
            'messages': 0,
            'sessions': 0,
            'voice_linked': 0,
            'cleared': None,
            'start_time': datetime.now().isoformat()
        }
        
        print("=" * 60)
        print("开始 ETL 数据导入")
        print(f"数据源: {self.db_base_path}")
        print(f"语音目录: {self.voice_base_path}")
        print(f"清除旧数据: {'是' if clear_existing else '否'}")
        print("=" * 60)

        self.validate_source_data()
        
        # 0. 清除旧数据（可选）
        if clear_existing:
            print("\n[Step 0] 清除旧数据...")
            stats['cleared'] = self.clear_existing_data(db_session)
        
        # 0.5. 加载语音文件列表
        print("\n[Step 0.5] 加载语音文件列表...")
        self.load_voice_files()
        
        # 1. 加载通讯录
        print("\n[Step 1] 加载通讯录...")
        contacts = self.load_contacts()
        stats['contacts'] = self.save_contacts(db_session, contacts)
        
        # 2. 加载群成员
        print("\n[Step 2] 加载群成员...")
        self.load_chatroom_members()
        
        # 3. 处理消息
        print("\n[Step 3] 处理聊天消息...")
        for i in range(6):  # MSG0 - MSG5
            try:
                count = self.process_messages(db_session, i)
                stats['messages'] += count
            except Exception as e:
                print(f"[ERROR] Failed to process MSG{i}.db: {e}")
        
        # 4. 构建会话
        print("\n[Step 4] 构建会话列表...")
        stats['sessions'] = self.build_sessions(db_session)
        
        # 5. 语音补链（ETL 后自动补充语音路径）
        print("\n[Step 5] 语音补链...")
        stats['voice_linked'] = self.relink_voice_files(db_session)
        
        stats['end_time'] = datetime.now().isoformat()
        
        print("\n" + "=" * 60)
        print("ETL 完成!")
        if stats['cleared']:
            print(f"  清除旧数据: raw_chats={stats['cleared']['raw_chats']}, sessions={stats['cleared']['sessions']}, contacts={stats['cleared']['contacts']}")
        print(f"  联系人: {stats['contacts']}")
        print(f"  消息数: {stats['messages']}")
        print(f"  会话数: {stats['sessions']}")
        print(f"  语音补链: {stats['voice_linked']}")
        print("=" * 60)
        
        return stats
