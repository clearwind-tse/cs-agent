# -*- coding: utf-8 -*-
"""
LLM 扩量脚本：把本平台微信模拟数据从种子量补到目标量。

复用 app.services.data_generator.DataGenerator（DeepSeek），
生成本平台客服对话并展开为微信 MSG 行，追加写入 Msg/Msg/Multi/MSG0.db。

用法：
    cd backend
    uv run python scripts/expand_wechat_data.py --target 300
"""
import argparse
import os
import random
import sqlite3
import sys

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.data_generator import DataGenerator, SCENARIO_TEMPLATES

BASE_TS = 1760490000  # 2025-10-15 09:00:00 CST，晚于 ETL 的 MIN_TIMESTAMP
DEFAULT_MSG_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "Msg", "Msg")
)


def parse_args():
    parser = argparse.ArgumentParser(description="本平台微信模拟数据 LLM 扩量")
    parser.add_argument("--target", type=int, default=300, help="目标消息总数（默认 300）")
    parser.add_argument("--msg-root", default=DEFAULT_MSG_ROOT, help="微信数据根目录")
    parser.add_argument("--max-attempts", type=int, default=60, help="最大 LLM 调用次数上限")
    return parser.parse_args()


def load_contact_wxids(msg_root: str):
    """从 MicroMsg.db 读取联系人 wxid 列表，用于给生成的对话分配会话。"""
    path = os.path.join(msg_root, "MicroMsg.db")
    if not os.path.exists(path):
        raise SystemExit(f"找不到通讯录: {path}（请先运行 scripts/generate_fake_data.py）")
    conn = sqlite3.connect(f"file:{path}?immutable=1", uri=True)
    try:
        wxids = [row[0] for row in conn.execute("SELECT UserName FROM Contact WHERE UserName IS NOT NULL")]
    finally:
        conn.close()
    if not wxids:
        raise SystemExit("通讯录为空，无法分配会话")
    return wxids


def append_conversations(msg_db: str, target: int, wxids, max_attempts: int) -> int:
    """生成对话并追加到 MSG0.db，返回追加的消息条数。"""
    generator = DataGenerator()
    if not generator.client:
        raise SystemExit("LLM 客户端未初始化，请检查 backend/.env 的 DEEPSEEK_API_KEY")

    conn = sqlite3.connect(msg_db)
    try:
        current = conn.execute("SELECT COUNT(*) FROM MSG").fetchone()[0]
        needed = target - current
        if needed <= 0:
            print(f"[INFO] 当前已有 {current} 条，已达到目标 {target}，无需扩量")
            return 0

        next_local = (conn.execute("SELECT COALESCE(MAX(localId), 0) FROM MSG").fetchone()[0]) + 1
        next_svr = (conn.execute("SELECT COALESCE(MAX(MsgSvrID), 0) FROM MSG").fetchone()[0]) + 1

        print(f"[INFO] 当前 {current} 条，目标 {target} 条，需追加约 {needed} 条")
        added = 0
        attempts = 0
        conversations = 0

        while added < needed and attempts < max_attempts:
            attempts += 1
            scenario = random.choice(SCENARIO_TEMPLATES)
            result, error = generator._generate_one(scenario)
            if not result:
                print(f"[WARN] 生成失败({attempts}): {scenario['title']} - {error}")
                continue

            conv = result["conversation_json"]
            wxid = random.choice(wxids)
            day_offset = random.randint(0, 60) * 86400

            for seq, msg in enumerate(conv):
                is_sender = 1 if msg["role"] == "assistant" else 0
                ts = BASE_TS + day_offset + seq * random.randint(30, 180)
                conn.execute(
                    "INSERT INTO MSG (localId, StrTalker, StrContent, CreateTime, Type, SubType, IsSender, DisplayContent, BytesExtra, MsgSvrID) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (next_local, wxid, msg["content"], ts, 1, 0, is_sender, None, None, next_svr),
                )
                next_local += 1
                next_svr += 1
                added += 1

            conversations += 1
            print(f"[OK] 生成第 {conversations} 段对话（{scenario['title']}），累计追加 {added} 条")

        conn.commit()
        print(f"[DONE] 追加 {conversations} 段对话 / {added} 条消息，当前总数 {current + added}")
        return added
    finally:
        conn.close()


def main():
    args = parse_args()
    msg_root = os.path.abspath(args.msg_root)
    msg_db = os.path.join(msg_root, "Multi", "MSG0.db")
    if not os.path.exists(msg_db):
        raise SystemExit(f"找不到消息库: {msg_db}（请先运行 scripts/generate_fake_data.py）")

    print("=" * 60)
    print("本平台微信模拟数据 LLM 扩量")
    print(f"消息库: {msg_db}")
    print("=" * 60)

    wxids = load_contact_wxids(msg_root)
    append_conversations(msg_db, args.target, wxids, args.max_attempts)


if __name__ == "__main__":
    main()
