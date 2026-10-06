# -*- coding: utf-8 -*-
"""
探索微信 SQLite 数据库表结构
"""
import sqlite3
import os
import sys

# 设置输出编码
sys.stdout.reconfigure(encoding='utf-8')

# 数据库路径
DB_BASE = os.path.join(os.path.dirname(__file__), '..', '..', 'Msg', 'Msg')

def list_tables(db_path):
    """列出数据库中的所有表"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [t[0] for t in cursor.fetchall()]
        conn.close()
        return tables
    except Exception as e:
        return [f"Error: {e}"]

def describe_table(db_path, table_name):
    """获取表结构"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        conn.close()
        return columns
    except Exception as e:
        return [f"Error: {e}"]

def sample_data(db_path, table_name, limit=3):
    """获取表中的示例数据"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(f"SELECT * FROM {table_name} LIMIT {limit}")
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception as e:
        return [f"Error: {e}"]

def count_rows(db_path, table_name):
    """统计表中的行数"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except Exception as e:
        return f"Error: {e}"

if __name__ == "__main__":
    print("=" * 60)
    print("探索微信数据库结构")
    print("=" * 60)
    
    # 1. 探索 MicroMsg.db (通讯录)
    print("\n[MicroMsg.db] 通讯录数据库")
    print("-" * 40)
    micromsg_path = os.path.join(DB_BASE, 'MicroMsg.db')
    tables = list_tables(micromsg_path)
    print(f"表数量: {len(tables)}")
    for t in tables:
        count = count_rows(micromsg_path, t)
        print(f"  - {t} ({count} rows)")
    
    # 重点看 Contact 表
    print("\n[Contact 表结构]:")
    columns = describe_table(micromsg_path, 'Contact')
    for col in columns:
        print(f"  {col[1]} ({col[2]})")
    
    print("\n[Contact 示例数据] (前3条):")
    samples = sample_data(micromsg_path, 'Contact', 3)
    for row in samples:
        print(f"  {row[:5]}...")  # 只显示前5个字段
    
    # 2. 探索 MSG0.db (聊天记录)
    print("\n" + "=" * 60)
    print("[MSG0.db] 聊天记录数据库")
    print("-" * 40)
    msg0_path = os.path.join(DB_BASE, 'Multi', 'MSG0.db')
    tables = list_tables(msg0_path)
    print(f"表数量: {len(tables)}")
    for t in tables:
        count = count_rows(msg0_path, t)
        print(f"  - {t} ({count} rows)")
    
    # 重点看 MSG 表
    print("\n[MSG 表结构]:")
    columns = describe_table(msg0_path, 'MSG')
    for col in columns:
        print(f"  {col[1]} ({col[2]})")
    
    print("\n[MSG 示例数据] (前3条, 文本消息 Type=1):")
    try:
        conn = sqlite3.connect(msg0_path)
        cursor = conn.execute("SELECT localId, StrTalker, StrContent, CreateTime, Type FROM MSG WHERE Type=1 LIMIT 3")
        samples = cursor.fetchall()
        conn.close()
        for row in samples:
            print(f"  ID: {row[0]}, Talker: {row[1][:20] if row[1] else 'None'}...")
            print(f"    Content: {row[2][:50] if row[2] else 'None'}...")
            print(f"    Time: {row[3]}, Type: {row[4]}")
    except Exception as e:
        print(f"  Error: {e}")
    
    # 3. 统计所有 MSG 数据库的消息数量
    print("\n" + "=" * 60)
    print("[所有 MSG 数据库统计]")
    print("-" * 40)
    total = 0
    for i in range(6):
        msg_path = os.path.join(DB_BASE, 'Multi', f'MSG{i}.db')
        if os.path.exists(msg_path):
            count = count_rows(msg_path, 'MSG')
            print(f"  MSG{i}.db: {count} 条消息")
            if isinstance(count, int):
                total += count
    print(f"\n  总计: {total} 条消息")
