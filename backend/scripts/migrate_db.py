# -*- coding: utf-8 -*-
"""
数据库迁移脚本
用于添加新字段和创建新表
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.database import get_engine, Base
from app.models.chat import RawChat, StagingConversation, LabeledConversation
from app.services.schema_sync import ensure_legacy_material_schema, ensure_legacy_raw_chat_schema, ensure_legacy_student_schema
from sqlalchemy import text, inspect

def migrate_database():
    """迁移数据库：添加新字段和创建新表"""
    engine = get_engine()
    inspector = inspect(engine)
    
    print("[INFO] Starting database migration...")
    
    # 1. 创建所有新表
    print("[1/3] Creating new tables...")
    try:
        Base.metadata.create_all(bind=engine)
        print("  [OK] Tables created/verified")
    except Exception as e:
        print(f"  [WARN] Table creation error: {e}")
    
    # 2. 检查并添加 RawChat 表的 status 字段
    print("[2/3] Checking RawChat table columns...")
    if 'raw_chats' in inspector.get_table_names():
        columns = [col['name'] for col in inspector.get_columns('raw_chats')]
        
        with engine.connect() as conn:
            # 添加 status 字段（如果不存在）
            if 'status' not in columns:
                print("  -> Adding 'status' column to raw_chats...")
                try:
                    conn.execute(text("ALTER TABLE raw_chats ADD COLUMN status VARCHAR(20) DEFAULT 'pending'"))
                    conn.commit()
                    print("  [OK] Added 'status' column")
                except Exception as e:
                    print(f"  [WARN] Failed to add status column: {e}")
                    conn.rollback()
            
            # 添加 clean_content 字段（如果不存在）
            if 'clean_content' not in columns:
                print("  -> Adding 'clean_content' column to raw_chats...")
                try:
                    conn.execute(text("ALTER TABLE raw_chats ADD COLUMN clean_content TEXT"))
                    conn.commit()
                    print("  [OK] Added 'clean_content' column")
                except Exception as e:
                    print(f"  [WARN] Failed to add clean_content column: {e}")
                    conn.rollback()
            
            # 添加其他新字段
            new_fields = {
                'auto_category': 'VARCHAR(50)',
                'auto_flags': 'TEXT',  # JSON stored as TEXT in SQLite
                'reviewed_by': 'VARCHAR(100)',
                'reviewed_at': 'DATETIME'
            }
            
            for field_name, field_type in new_fields.items():
                if field_name not in columns:
                    print(f"  -> Adding '{field_name}' column to raw_chats...")
                    try:
                        conn.execute(text(f"ALTER TABLE raw_chats ADD COLUMN {field_name} {field_type}"))
                        conn.commit()
                        print(f"  [OK] Added '{field_name}' column")
                    except Exception as e:
                        print(f"  [WARN] Failed to add {field_name} column: {e}")
                        conn.rollback()
    else:
        print("  [INFO] raw_chats table does not exist, will be created")

    added_columns = ensure_legacy_raw_chat_schema(engine)
    if added_columns:
        print(f"  [OK] Added legacy media columns: {', '.join(added_columns)}")

    added_material_columns = ensure_legacy_material_schema(engine)
    if added_material_columns:
        print(f"  [OK] Added legacy material columns: {', '.join(added_material_columns)}")

    added_student_columns = ensure_legacy_student_schema(engine)
    if added_student_columns:
        print(f"  [OK] Added legacy student columns: {', '.join(added_student_columns)}")
    
    # 3. 创建索引（如果不存在）
    print("[3/3] Creating indexes...")
    try:
        with engine.connect() as conn:
            # 检查并创建 status 索引
            indexes = [idx['name'] for idx in inspector.get_indexes('raw_chats')] if 'raw_chats' in inspector.get_table_names() else []
            if 'idx_status_session' not in indexes:
                try:
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_status_session ON raw_chats(status, session_id)"))
                    conn.commit()
                    print("  [OK] Created index idx_status_session")
                except Exception as e:
                    print(f"  [WARN] Failed to create index: {e}")
    except Exception as e:
        print(f"  [WARN] Index creation error: {e}")
    
    print("[INFO] Database migration completed!")
    print("[INFO] Please restart the backend service.")

if __name__ == "__main__":
    migrate_database()
