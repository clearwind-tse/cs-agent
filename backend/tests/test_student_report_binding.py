import os
import sys
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.models.database import Base
from app.models.chat import Material
from app.models.student import Student
from app.models.student_report_binding import StudentReportBinding
from fastapi import HTTPException

from app.services.student_reports import (
    add_student_report,
    bind_main_report_material,
    build_student_response,
    ensure_material_not_bound,
    get_material_bound_students_map,
    get_student_report_materials,
    remove_student_report,
    serialize_material_response,
    serialize_student_response,
    set_primary_report,
    unbind_main_report_material,
)


class _TestHelper:
    """Mixin methods for creating test fixtures."""

    _created_student_ids: list
    _created_material_ids: list

    def _make_report(self, filename='report.png'):
        report = Material(
            filename=filename,
            stored_name=f'stored-{filename}',
            file_size=1234,
            file_type='image/png',
            category='report',
        )
        self.db.add(report)
        self.db.flush()
        self._created_material_ids.append(report.id)
        return report

    def _make_student(self, name='张三'):
        student = Student(name=name, channel='微信')
        self.db.add(student)
        self.db.flush()
        self._created_student_ids.append(student.id)
        return student


class StudentReportBindingTests(_TestHelper, unittest.TestCase):
    def setUp(self):
        db_url = os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres@db:5432/agent_cs_playbook')
        engine = create_engine(db_url)
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(bind=engine)
        self.db = self.SessionLocal()
        self._created_student_ids: list[int] = []
        self._created_material_ids: list[int] = []

    def tearDown(self):
        # 清理测试数据
        try:
            for sid in self._created_student_ids:
                self.db.query(StudentReportBinding).filter(StudentReportBinding.student_id == sid).delete()
            for mid in self._created_material_ids:
                self.db.query(StudentReportBinding).filter(StudentReportBinding.material_id == mid).delete()
            for sid in self._created_student_ids:
                self.db.query(Student).filter(Student.id == sid).delete()
            for mid in self._created_material_ids:
                self.db.query(Material).filter(Material.id == mid).delete()
            self.db.commit()
        except Exception:
            self.db.rollback()
        finally:
            self.db.close()

    # ---- 基本绑定 ----

    def test_bind_report_to_student(self):
        report = self._make_report()
        student = self._make_student('李四')
        self.db.commit()

        s, r = add_student_report(self.db, student.id, report.id)
        self.assertEqual(r.id, report.id)
        # 第一张自动设为主喜报
        binding = self.db.query(StudentReportBinding).filter_by(student_id=student.id).first()
        self.assertTrue(binding.is_primary)
        self.assertEqual(s.main_report_material_id, report.id)

    def test_bind_multiple_reports(self):
        r1 = self._make_report('r1.png')
        r2 = self._make_report('r2.png')
        r3 = self._make_report('r3.png')
        student = self._make_student('王五')
        self.db.commit()

        add_student_report(self.db, student.id, r1.id)
        add_student_report(self.db, student.id, r2.id)
        add_student_report(self.db, student.id, r3.id)

        reports, primary = get_student_report_materials(self.db, student.id)
        self.assertEqual(len(reports), 3)
        self.assertEqual(primary.id, r1.id)  # 第一张是主喜报

    def test_reject_duplicate_binding(self):
        report = self._make_report()
        student = self._make_student()
        self.db.commit()

        add_student_report(self.db, student.id, report.id)
        with self.assertRaises(HTTPException) as ctx:
            add_student_report(self.db, student.id, report.id)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_reject_binding_non_report_material(self):
        material = Material(
            filename='course.pdf',
            stored_name='stored-course.pdf',
            file_size=1234,
            file_type='application/pdf',
            category='course',
        )
        student = self._make_student()
        self.db.add(material)
        self.db.flush()
        self._created_material_ids.append(material.id)
        self.db.commit()

        with self.assertRaises(HTTPException) as ctx:
            add_student_report(self.db, student.id, material.id)
        self.assertEqual(ctx.exception.status_code, 400)

    # ---- 互斥校验 ----

    def test_reject_binding_report_already_used_by_other_student(self):
        report = self._make_report()
        s1 = self._make_student('张三')
        s2 = self._make_student('李四')
        self.db.commit()

        add_student_report(self.db, s1.id, report.id)
        with self.assertRaises(HTTPException) as ctx:
            add_student_report(self.db, s2.id, report.id)
        self.assertEqual(ctx.exception.status_code, 409)

    # ---- 解绑 ----

    def test_remove_non_primary_report(self):
        r1 = self._make_report('r1.png')
        r2 = self._make_report('r2.png')
        student = self._make_student()
        self.db.commit()

        add_student_report(self.db, student.id, r1.id)
        add_student_report(self.db, student.id, r2.id)
        remove_student_report(self.db, student.id, r2.id)

        reports, primary = get_student_report_materials(self.db, student.id)
        self.assertEqual(len(reports), 1)
        self.assertEqual(primary.id, r1.id)  # 主喜报不变

    def test_remove_primary_promotes_next(self):
        """移除主喜报后，自动将下一张升为主喜报。"""
        r1 = self._make_report('r1.png')
        r2 = self._make_report('r2.png')
        student = self._make_student()
        self.db.commit()

        add_student_report(self.db, student.id, r1.id)
        add_student_report(self.db, student.id, r2.id)
        remove_student_report(self.db, student.id, r1.id)

        reports, primary = get_student_report_materials(self.db, student.id)
        self.assertEqual(len(reports), 1)
        self.assertIsNotNone(primary)
        self.assertEqual(primary.id, r2.id)

    def test_remove_only_report_clears_primary(self):
        report = self._make_report()
        student = self._make_student()
        self.db.commit()

        add_student_report(self.db, student.id, report.id)
        remove_student_report(self.db, student.id, report.id)

        self.db.refresh(student)
        self.assertIsNone(student.main_report_material_id)
        reports, primary = get_student_report_materials(self.db, student.id)
        self.assertEqual(len(reports), 0)
        self.assertIsNone(primary)

    # ---- 设置主喜报 ----

    def test_set_primary_report(self):
        r1 = self._make_report('r1.png')
        r2 = self._make_report('r2.png')
        student = self._make_student()
        self.db.commit()

        add_student_report(self.db, student.id, r1.id)
        add_student_report(self.db, student.id, r2.id)
        set_primary_report(self.db, student.id, r2.id)

        reports, primary = get_student_report_materials(self.db, student.id)
        self.assertEqual(primary.id, r2.id)
        self.db.refresh(student)
        self.assertEqual(student.main_report_material_id, r2.id)

        # r1 不再是主喜报
        r1_binding = self.db.query(StudentReportBinding).filter_by(
            student_id=student.id, material_id=r1.id
        ).first()
        self.assertFalse(r1_binding.is_primary)

    # ---- 序列化 ----

    def test_student_response_includes_report_materials(self):
        r1 = self._make_report('r1.png')
        r2 = self._make_report('r2.png')
        student = self._make_student()
        self.db.commit()

        add_student_report(self.db, student.id, r1.id)
        add_student_report(self.db, student.id, r2.id)

        result = build_student_response(self.db, student)
        self.assertEqual(result['main_report_material_id'], r1.id)
        self.assertIsNotNone(result['main_report_material'])
        self.assertEqual(len(result['report_materials']), 2)
        self.assertTrue(result['report_materials'][0]['is_primary'])
        self.assertFalse(result['report_materials'][1]['is_primary'])

    def test_material_response_includes_bound_students(self):
        report = self._make_report()
        student = self._make_student('周八')
        self.db.commit()

        add_student_report(self.db, student.id, report.id)
        result = serialize_material_response(report, [student])

        self.assertEqual(result['bound_student_id'], student.id)
        self.assertEqual(result['bound_student_name'], student.name)
        self.assertEqual(len(result['bound_students']), 1)

    def test_get_material_bound_students_map(self):
        r1 = self._make_report('a.png')
        r2 = self._make_report('b.png')
        student = self._make_student('吴九')
        self.db.commit()

        add_student_report(self.db, student.id, r1.id)
        result = get_material_bound_students_map(self.db, [r1.id, r2.id])

        self.assertIn(r1.id, result)
        self.assertEqual(result[r1.id][0].name, student.name)
        self.assertNotIn(r2.id, result)

    # ---- 删除保护 ----

    def test_reject_delete_bound_material(self):
        report = self._make_report()
        student = self._make_student('郑十')
        self.db.commit()

        add_student_report(self.db, student.id, report.id)
        with self.assertRaises(HTTPException) as ctx:
            ensure_material_not_bound(self.db, report.id)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_allow_delete_unbound_material(self):
        report = self._make_report()
        self.db.commit()
        # 不应抛异常
        ensure_material_not_bound(self.db, report.id)

    # ---- 兼容旧接口 ----

    def test_legacy_bind_creates_primary(self):
        report = self._make_report()
        student = self._make_student()
        self.db.commit()

        s, r = bind_main_report_material(self.db, student.id, report.id)
        self.assertEqual(s.main_report_material_id, report.id)
        binding = self.db.query(StudentReportBinding).filter_by(
            student_id=student.id, material_id=report.id
        ).first()
        self.assertIsNotNone(binding)
        self.assertTrue(binding.is_primary)

    def test_legacy_unbind_removes_primary(self):
        report = self._make_report()
        student = self._make_student()
        self.db.commit()

        bind_main_report_material(self.db, student.id, report.id)
        s = unbind_main_report_material(self.db, student.id)
        self.assertIsNone(s.main_report_material_id)


if __name__ == '__main__':
    unittest.main()
