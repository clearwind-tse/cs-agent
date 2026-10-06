# -*- coding: utf-8 -*-
"""
运行 ETL 数据导入脚本
将微信 SQLite 数据导入 PostgreSQL
"""
import argparse
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.models.database import get_session_local, get_engine, Base
from app.services.etl import WeChatETL


def parse_args():
    parser = argparse.ArgumentParser(description="Agent CS Playbook ETL Data Import Tool")
    parser.add_argument(
        "--clear-existing",
        action="store_true",
        help="导入前先清空现有 raw_chats / sessions / contacts，用于和线上同口径全量重建",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    print("=" * 60)
    print("Agent CS Playbook ETL Data Import Tool")
    print("=" * 60)
    
    # Create database tables
    print("\n[Step 0] Creating database tables...")
    engine = get_engine()
    
    # 尝试启用 pgvector 扩展（仅 PostgreSQL 有效，SQLite 会跳过）
    import sqlalchemy
    try:
        with engine.connect() as conn:
            conn.execute(sqlalchemy.text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
            print("[INFO] pgvector extension enabled")
    except Exception as e:
        print(f"[INFO] pgvector extension skipped (non-PostgreSQL or not available): {e}")
        
    Base.metadata.create_all(bind=engine)
    print("[INFO] Database tables created")
    
    # Create database session
    SessionLocal = get_session_local()
    db = SessionLocal()
    
    try:
        # 运行 ETL
        etl = WeChatETL()
        stats = etl.run_full_etl(db, clear_existing=args.clear_existing)
        
        print("\n" + "=" * 60)
        print("导入完成! 统计信息:")
        print(f"  - 联系人: {stats['contacts']}")
        print(f"  - 消息数: {stats['messages']}")
        print(f"  - 会话数: {stats['sessions']}")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n[ERROR] ETL 失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
