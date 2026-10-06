import os
import sys
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.models.chat import Material
from app.models.database import Base, get_db
from app.routers.materials import router


class MaterialFolderMoveTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        self.db = self.SessionLocal()

        app = FastAPI()
        app.include_router(router)

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.db.close()

    def _create_material(self, *, category="report", file_type="image/png", folder_id=None, filename="report.png"):
        material = Material(
            filename=filename,
            stored_name=f"stored-{filename}",
            file_size=1234,
            file_type=file_type,
            category=category,
            title=filename,
            description="",
            tags=[],
            uploaded_by="tester",
            download_count=0,
            folder_id=folder_id,
        )
        self.db.add(material)
        self.db.commit()
        self.db.refresh(material)
        return material

    def test_move_report_material_to_folder_success(self):
        folder = self._create_material(category="report", file_type="folder", filename="喜报文件夹")
        material = self._create_material(category="report")

        response = self.client.put(f"/api/materials/{material.id}/move", json={"folder_id": folder.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], material.id)
        self.assertEqual(response.json()["folder_id"], folder.id)

        self.db.expire_all()
        moved = self.db.query(Material).filter(Material.id == material.id).first()
        self.assertEqual(moved.folder_id, folder.id)

    def test_move_report_material_to_root_success(self):
        folder = self._create_material(category="report", file_type="folder", filename="喜报文件夹")
        material = self._create_material(category="report", folder_id=folder.id)

        response = self.client.put(f"/api/materials/{material.id}/move", json={"folder_id": None})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["folder_id"], None)

        self.db.expire_all()
        moved = self.db.query(Material).filter(Material.id == material.id).first()
        self.assertIsNone(moved.folder_id)

    def test_reject_move_for_non_report_material(self):
        folder = self._create_material(category="course", file_type="folder", filename="课程文件夹")
        material = self._create_material(category="course", filename="course.pdf", file_type="application/pdf")

        response = self.client.put(f"/api/materials/{material.id}/move", json={"folder_id": folder.id})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "仅支持移动喜报素材")

    def test_reject_move_for_folder_material(self):
        source_folder = self._create_material(category="report", file_type="folder", filename="源文件夹")
        target_folder = self._create_material(category="report", file_type="folder", filename="目标文件夹")

        response = self.client.put(f"/api/materials/{source_folder.id}/move", json={"folder_id": target_folder.id})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "文件夹素材不支持移动")

    def test_reject_move_to_same_folder(self):
        folder = self._create_material(category="report", file_type="folder", filename="喜报文件夹")
        material = self._create_material(category="report", folder_id=folder.id)

        response = self.client.put(f"/api/materials/{material.id}/move", json={"folder_id": folder.id})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "素材已在当前目录")

    def test_reject_move_to_folder_in_other_category(self):
        folder = self._create_material(category="course", file_type="folder", filename="课程文件夹")
        material = self._create_material(category="report")

        response = self.client.put(f"/api/materials/{material.id}/move", json={"folder_id": folder.id})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "不能移动到其他分类的文件夹")


if __name__ == "__main__":
    unittest.main()
