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
        ('push_source', 'VARCHAR(20)'),
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


def _add_missing_columns(engine, table: str, required: list[tuple[str, str]]) -> list[str]:
    """通用：为指定表补齐缺失列，返回新增列名。"""
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return []
    existing = {col['name'] for col in inspector.get_columns(table)}
    missing = [(n, t) for n, t in required if n not in existing]
    if not missing:
        return []
    added: list[str] = []
    with engine.connect() as conn:
        for name, ctype in missing:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ctype}"))
            added.append(name)
        conn.commit()
    return added


def ensure_session_schema(engine) -> list[str]:
    """为旧版 sessions 表补齐 push_source（来源标记）。"""
    return _add_missing_columns(
        engine, 'sessions',
        [('push_source', 'VARCHAR(20)')],
    )


def ensure_agent_session_schema(engine) -> list[str]:
    """为旧版 agent_sessions 表补齐生命周期字段 status / closed_at。"""
    return _add_missing_columns(
        engine, 'agent_sessions',
        [('status', 'VARCHAR(20)'), ('closed_at', 'TIMESTAMP')],
    )


def ensure_media_asset_schema(engine) -> list[str]:
    """
    为旧版 media_assets 补二级目录列。
    create_all 只建新表、不改旧表，所以这列必须显式 ALTER；
    补完再建索引（新表由 create_all 建过，IF NOT EXISTS 保证幂等）。
    """
    inspector = inspect(engine)
    if 'media_assets' not in inspector.get_table_names():
        return []
    added = _add_missing_columns(engine, 'media_assets', [('category', 'VARCHAR(40)')])
    existing_indexes = {idx['name'] for idx in inspector.get_indexes('media_assets')}
    if 'ix_media_assets_category' not in existing_indexes:
        with engine.connect() as conn:
            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_media_assets_category ON media_assets(category)'))
            conn.commit()
    return added


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
