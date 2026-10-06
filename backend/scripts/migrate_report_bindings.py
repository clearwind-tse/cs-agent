#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据迁移脚本：将现有 students.main_report_material_id 迁移到 student_report_bindings 中间表。

用法：
    python backend/scripts/migrate_report_bindings.py

特性：
    - 幂等执行（已存在的绑定会跳过）
    - 迁移后不删除 main_report_material_id 字段（保持向后兼容）
"""
import sys
import os

# 确保能导入 backend 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.models.database import get_engine, get_session_local, Base
from app.models.student import Student
from app.models.student_report_binding import StudentReportBinding


def migrate():
    engine = get_engine()

    # 确保中间表存在
    Base.metadata.create_all(bind=engine)

    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        # 查找所有有主喜报的学生
        students_with_report = (
            db.query(Student)
            .filter(Student.main_report_material_id.isnot(None))
            .all()
        )

        if not students_with_report:
            print("[INFO] 没有需要迁移的数据")
            return

        migrated = 0
        skipped = 0

        for student in students_with_report:
            # 检查是否已存在
            existing = (
                db.query(StudentReportBinding)
                .filter(
                    StudentReportBinding.student_id == student.id,
                    StudentReportBinding.material_id == student.main_report_material_id,
                )
                .first()
            )
            if existing:
                skipped += 1
                continue

            binding = StudentReportBinding(
                student_id=student.id,
                material_id=student.main_report_material_id,
                is_primary=True,
                sort_order=0,
            )
            db.add(binding)
            migrated += 1

        db.commit()
        print(f"[INFO] 迁移完成: 新增 {migrated} 条绑定, 跳过 {skipped} 条已存在绑定")
        print(f"[INFO] 总计 {len(students_with_report)} 个学生有主喜报记录")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] 迁移失败: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
