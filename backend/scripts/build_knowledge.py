# -*- coding: utf-8 -*-
"""
全量构建知识库脚本
独立运行，不受 HTTP 超时限制
用法: python scripts/build_knowledge.py [--limit N] [--batch N]
"""
import sys
import os
import time
import argparse

# 将 backend 目录加入 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.database import get_session_local
from app.services.knowledge import KnowledgeBuilder
from app.models.chat import Session


def main():
    parser = argparse.ArgumentParser(description='构建知识库')
    parser.add_argument('--limit', type=int, default=0, help='限制会话数量，0表示全部')
    parser.add_argument('--batch', type=int, default=50, help='每批处理数量')
    parser.add_argument('--no-filter', action='store_true', help='不过滤消息')
    args = parser.parse_args()

    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        builder = KnowledgeBuilder(db, use_filter=not args.no_filter)

        query = db.query(Session)
        if args.limit > 0:
            query = query.limit(args.limit)

        sessions = query.all()
        total = len(sessions)
        print(f"\n{'='*50}")
        print(f"  知识库构建")
        print(f"  总会话数: {total}")
        print(f"  过滤: {'关闭' if args.no_filter else '开启'}")
        print(f"{'='*50}\n")

        total_chunks = 0
        success = 0
        errors = 0
        start_time = time.time()

        for i, session in enumerate(sessions):
            try:
                count = builder.build_chunks_for_session(session.session_id)
                if count > 0:
                    total_chunks += count
                    success += 1
                    print(f"  [{i+1}/{total}] ✓ {session.session_id}: {count} chunks")

                # 每批次提交
                if (i + 1) % args.batch == 0:
                    db.commit()
                    elapsed = time.time() - start_time
                    speed = (i + 1) / elapsed
                    remaining = (total - i - 1) / speed if speed > 0 else 0
                    print(f"\n  --- 进度: {i+1}/{total} | "
                          f"已创建: {total_chunks} chunks | "
                          f"耗时: {elapsed:.0f}s | "
                          f"预计剩余: {remaining:.0f}s ---\n")

            except Exception as e:
                errors += 1
                print(f"  [{i+1}/{total}] ✗ {session.session_id}: {str(e)[:100]}")

        # 最后提交
        db.commit()
        elapsed = time.time() - start_time

        print(f"\n{'='*50}")
        print(f"  构建完成!")
        print(f"  总耗时: {elapsed:.1f}s")
        print(f"  成功会话: {success}/{total}")
        print(f"  创建知识块: {total_chunks}")
        print(f"  错误: {errors}")
        print(f"{'='*50}\n")

    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == '__main__':
    main()
