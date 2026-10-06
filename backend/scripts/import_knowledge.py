# -*- coding: utf-8 -*-
"""
将知识库 CSV 和话术库 CSV 导入到数据库的 knowledge_articles 表

用法:
    cd backend
    python scripts/import_knowledge.py ../rag_knowledge_base.csv --type knowledge
    python scripts/import_knowledge.py ../rag_script_library.csv --type script
"""
import csv
import sys
import os
import argparse

# 添加 backend 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def import_knowledge_csv(csv_path: str, source_type: str = 'knowledge'):
    """导入知识库 CSV 到 knowledge_articles 表"""
    from app.models.database import get_session_local
    from app.models.chat import KnowledgeArticle
    from app.services.embedding import get_embedding_service

    SessionLocal = get_session_local()
    db = SessionLocal()
    embedding_service = get_embedding_service()

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))

    print(f"读取 {len(rows)} 条记录 (type={source_type})")

    imported = 0
    failed = 0

    for i, row in enumerate(rows):
        try:
            question = row.get('question', '')
            answer = row.get('answer', '')
            intent = row.get('intent', '')
            tags = row.get('tags', '')
            source = row.get('source', '')
            variants = row.get('variants', '')

            if not question or not answer:
                continue

            # 解析 tags
            if isinstance(tags, str):
                tags_list = [t.strip() for t in tags.split(',') if t.strip()]
            else:
                tags_list = []

            # 生成 embedding（用 question + answer 的前100字拼接）
            embed_text = f"{question} {answer[:100]}"
            try:
                embedding = embedding_service.embed_text(embed_text)
            except Exception as e:
                print(f"  [{i+1}] Embedding 失败: {e}")
                embedding = None

            # 构建关键要点
            key_points = tags_list

            # 构建 scene（用于 RAG 匹配展示）
            if source_type == 'knowledge':
                scene = f"[{intent}] {question}"
            else:
                scene = f"[话术] {question[:50]}"

            article = KnowledgeArticle(
                scene=scene,
                scene_category=intent or 'sales',
                customer_says=question,
                recommended_response=answer,
                key_points=key_points,
                embedding=embedding,
                source_type=source_type,
                confidence=float(row.get('confidence', 0.8)) if source_type == 'script' else 0.95,
                is_verified=(source_type == 'knowledge'),  # 知识库条目标记为已验证
            )

            db.add(article)
            imported += 1

            if (i + 1) % 50 == 0:
                db.commit()
                print(f"  已导入 {imported}/{len(rows)}...")

        except Exception as e:
            print(f"  [{i+1}] 错误: {e}")
            failed += 1
            continue

    db.commit()
    db.close()

    print(f"\n导入完成: {imported} 成功, {failed} 失败")
    return imported


def main():
    parser = argparse.ArgumentParser(description='导入知识库/话术库到数据库')
    parser.add_argument('csv_path', help='CSV 文件路径')
    parser.add_argument('--type', choices=['knowledge', 'script', 'labeled'],
                        default='knowledge', help='数据类型')
    parser.add_argument('--clear', action='store_true',
                        help='导入前清空同类型数据')
    args = parser.parse_args()

    if args.clear:
        from app.models.database import get_session_local
        from app.models.chat import KnowledgeArticle
        SessionLocal = get_session_local()
        db = SessionLocal()
        deleted = db.query(KnowledgeArticle).filter(
            KnowledgeArticle.source_type == args.type
        ).delete()
        db.commit()
        db.close()
        print(f"已清空 {deleted} 条 {args.type} 类型数据")

    import_knowledge_csv(args.csv_path, args.type)


if __name__ == '__main__':
    main()
