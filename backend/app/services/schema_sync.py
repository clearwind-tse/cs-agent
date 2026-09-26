# -*- coding: utf-8 -*-
"""
数据库旧表结构兼容修复
"""
from collections.abc import Iterable

from sqlalchemy import inspect, text


def get_missing_raw_chat_columns(existing_columns: Iterable[str]) -> list[tuple[str, str]]:
    """返回旧 raw_chats 表需要补齐的媒体相关字段。"""
    existing = set(existing_columns)
    required_columns = [
        ('msg_server_id', 'BIGINT'),
        ('voice_path', 'VARCHAR(300)'),
    ]
    return [(name, column_type) for name, column_type in required_columns if name not in existing]


def ensure_legacy_raw_chat_schema(engine) -> list[str]:
    """
    为旧版 raw_chats 表补齐后续代码依赖的字段。
    返回本次新增的列名列表。
    """
    inspector = inspect(engine)
    if 'raw_chats' not in inspector.get_table_names():
        return []

    existing_columns = [col['name'] for col in inspector.get_columns('raw_chats')]
    missing_columns = get_missing_raw_chat_columns(existing_columns)
    if not missing_columns:
        return []

    added_columns: list[str] = []
    with engine.connect() as conn:
        for column_name, column_type in missing_columns:
            conn.execute(text(f"ALTER TABLE raw_chats ADD COLUMN {column_name} {column_type}"))
            added_columns.append(column_name)

        conn.commit()

        existing_indexes = {idx['name'] for idx in inspect(engine).get_indexes('raw_chats')}
        if 'msg_server_id' in added_columns and 'ix_raw_chats_msg_server_id' not in existing_indexes:
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_raw_chats_msg_server_id ON raw_chats(msg_server_id)"))
            conn.commit()

    return added_columns


def ensure_ticket_schema(engine) -> list[str]:
    """
    为旧版 tickets 表补齐工单系统新增字段（SLA / 解决时间 / 处理结论）。
    返回本次新增的列名列表。
    """
    inspector = inspect(engine)
    if 'tickets' not in inspector.get_table_names():
        return []

    existing_columns = [col['name'] for col in inspector.get_columns('tickets')]
    required_columns = [
        ('sla_due_at', 'TIMESTAMP'),
        ('resolved_at', 'TIMESTAMP'),
        ('resolution', 'TEXT'),
    ]
    missing_columns = [(n, t) for n, t in required_columns if n not in existing_columns]
    if not missing_columns:
        return []

    added_columns: list[str] = []
    with engine.connect() as conn:
        for column_name, column_type in missing_columns:
            conn.execute(text(f"ALTER TABLE tickets ADD COLUMN {column_name} {column_type}"))
            added_columns.append(column_name)
        conn.commit()
    return added_columns
