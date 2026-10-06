# -*- coding: utf-8 -*-
"""
迁移脚本：为 custom_conversations 表添加 system_prompt 列
"""
import sqlite3
import os
import sys

# 添加项目路径
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from app.config import get_settings


def migrate():
    """添加 system_prompt 列"""
    settings = get_settings()
    database_url = settings.database_url

    # 从 DATABASE_URL 获取数据库路径
    if database_url.startswith("sqlite:///"):
        db_path = database_url.replace("sqlite:///", "")
        # 处理相对路径
        if db_path.startswith("./"):
            db_path = os.path.join(backend_dir, db_path[2:])
    else:
        print(f"不支持的数据库类型: {database_url}")
        print("如果使用 PostgreSQL，请手动执行: ALTER TABLE custom_conversations ADD COLUMN system_prompt TEXT;")
        return

    print(f"数据库路径: {db_path}")

    if not os.path.exists(db_path):
        print(f"数据库文件不存在: {db_path}")
        print("数据库表将在首次使用时自动创建")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 检查表是否存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='custom_conversations'")
        if not cursor.fetchone():
            print("custom_conversations 表不存在，将在首次使用时自动创建")
            return

        # 检查列是否已存在
        cursor.execute("PRAGMA table_info(custom_conversations)")
        columns = [col[1] for col in cursor.fetchall()]

        if "system_prompt" in columns:
            print("system_prompt 列已存在，无需迁移")
            return

        # 添加列
        cursor.execute("ALTER TABLE custom_conversations ADD COLUMN system_prompt TEXT")
        conn.commit()
        print("成功添加 system_prompt 列!")

    except sqlite3.OperationalError as e:
        print(f"迁移失败: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
