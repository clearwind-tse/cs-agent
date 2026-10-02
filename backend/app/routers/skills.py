# -*- coding: utf-8 -*-
"""
技能（Skill）管理路由

设计参考 DataClaw backend/app/api/skills.py：
- 存储在 data/skills.json（JSON 文件，无 DB 表）
- 每个 skill 对应 workspace/skills/{id}/SKILL.md 文件夹（便于 Claude Code 读取）
- 来源：system_builtin（内嵌）、backend_generated（后端生成）、local_import（手动导入）
"""
import json
import os
import shutil
import re
from pathlib import Path
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Form
from pydantic import BaseModel, Field

from app.core.data_root import get_data_root, get_workspace_root

router = APIRouter(prefix="/api/skills", tags=["skills"])

SKILLS_FILE = str(get_data_root() / "skills.json")
SKILL_HUB_DIR = str(get_workspace_root() / "skills")
BACKEND_BUILTIN_SKILLS_DIR = str(Path(__file__).resolve().parents[1] / "skills_builtin")

SOURCE_LOCAL_IMPORT = "local_import"
SOURCE_BACKEND_GENERATED = "backend_generated"
SOURCE_SYSTEM_BUILTIN = "system_builtin"
SOURCE_UPLOADED_FILE = "uploaded_file"

_STATUS_SAFE = "safe"
_STATUS_LOW_RISK = "low_risk"


# ==================== Pydantic 模型 ====================

class SkillItem(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    content: str
    type: str = "agentskill"
    project_id: Optional[int] = None
    source: str = SOURCE_LOCAL_IMPORT
    installation_time: str = ""
    status: str = _STATUS_SAFE
    file_path: Optional[str] = None
    is_builtin: bool = False


class SkillCreate(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    content: str
    type: str = "agentskill"
    project_id: Optional[int] = None
    source: str = SOURCE_LOCAL_IMPORT
    status: str = _STATUS_SAFE
    file_path: Optional[str] = None


class SkillUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    type: Optional[str] = None
    project_id: Optional[int] = None
    status: Optional[str] = None


# ==================== 工具函数 ====================

def _load_data() -> List[dict]:
    if not os.path.exists(SKILLS_FILE):
        return []
    try:
        with open(SKILLS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def _save_data(data: List[dict]):
    os.makedirs(os.path.dirname(SKILLS_FILE), exist_ok=True)
    with open(SKILLS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _parse_skill_md(file_path: str) -> dict:
    """解析 SKILL.md 的 frontmatter + body"""
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"[Skills] 读取失败 {file_path}: {e}")
        return {}

    metadata: dict = {}
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            import yaml
            try:
                metadata = yaml.safe_load(parts[1]) or {}
                body = parts[2].strip()
            except Exception:
                pass

    return {
        "name": metadata.get("name"),
        "description": metadata.get("description"),
        "content": body,
        "metadata": metadata,
    }


def _safe_dir_name(value: str) -> str:
    safe = re.sub(r'[^a-zA-Z0-9_\-]', '_', value or "").lower()
    return safe or "skill"


def _write_skill_markdown(skill_dir: str, name: str, description: Optional[str], content: str) -> str:
    os.makedirs(skill_dir, exist_ok=True)
    path = os.path.join(skill_dir, "SKILL.md")
    desc = description or "No description"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"---\nname: {name}\ndescription: {desc}\n---\n\n{content}\n")
    return path


def _scan_builtin(data: List[dict], source_dir: str, source_name: str):
    """扫描内置技能目录，合并到 data"""
    if not os.path.exists(source_dir):
        return
    registered: set = {os.path.abspath(d.get("file_path", "")) for d in data if d.get("file_path")}
    for item in sorted(os.listdir(source_dir)):
        skill_dir = os.path.abspath(os.path.join(source_dir, item))
        if not os.path.isdir(skill_dir):
            continue
        md_path = os.path.join(skill_dir, "SKILL.md")
        if not os.path.exists(md_path):
            continue
        info = _parse_skill_md(md_path)
        name = info.get("name") or item
        # 查找已有记录
        existing = next((d for d in data if d.get("file_path") == skill_dir), None)
        entry = {
            "id": item,
            "name": name,
            "description": info.get("description") or "No description",
            "content": info.get("content") or "",
            "type": "agentskill",
            "project_id": None,
            "source": source_name,
            "installation_time": datetime.now().strftime("%Y年%m月%d日"),
            "status": _STATUS_SAFE,
            "file_path": skill_dir,
            "is_builtin": True,
        }
        if existing:
            existing.update(entry)
        else:
            data.append(entry)
            registered.add(skill_dir)


def _ensure_hub_dir():
    os.makedirs(SKILL_HUB_DIR, exist_ok=True)


def load_skills(project_id: Optional[int] = None) -> List[dict]:
    _ensure_hub_dir()
    data = _load_data()

    # 规范化已有条目的 source/status
    for item in data:
        item["source"] = item.get("source", SOURCE_LOCAL_IMPORT)
        item["status"] = item.get("status", _STATUS_SAFE)
        if item.get("id") in ("nl2sql", "visualization") or item.get("is_builtin"):
            item["is_builtin"] = True

    # 扫描 builtin 目录
    _scan_builtin(data, BACKEND_BUILTIN_SKILLS_DIR, SOURCE_SYSTEM_BUILTIN)

    # 扫描 workspace/skills 下未注册的
    for item in sorted(os.listdir(SKILL_HUB_DIR)):
        skill_dir = os.path.abspath(os.path.join(SKILL_HUB_DIR, item))
        if not os.path.isdir(skill_dir):
            continue
        md_path = os.path.join(skill_dir, "SKILL.md")
        if not os.path.exists(md_path):
            continue
        if any(d.get("file_path") == skill_dir for d in data):
            continue
        info = _parse_skill_md(md_path)
        name = info.get("name") or item
        # 尝试从目录名前缀提取 project_id（p{number}_xxx）
        pid: Optional[int] = None
        m = re.match(r'^p(\d+)_', item)
        if m:
            pid = int(m.group(1))
        data.append({
            "id": item,
            "name": name,
            "description": info.get("description") or "No description",
            "content": info.get("content") or "",
            "type": "agentskill",
            "project_id": pid,
            "source": SOURCE_BACKEND_GENERATED,
            "installation_time": datetime.now().strftime("%Y年%m月%d日"),
            "status": _STATUS_SAFE,
            "file_path": skill_dir,
            "is_builtin": False,
        })

    # 去重（按 id）
    seen: dict = {}
    for d in data:
        seen[d["id"]] = d
    data = list(seen.values())

    if project_id is not None:
        data = [d for d in data if d.get("project_id") == project_id or d.get("project_id") is None]
    return data


# ==================== API 端点 ====================

@router.get("")
def list_skills(project_id: Optional[int] = None):
    """列出所有技能"""
    return load_skills(project_id)


@router.get("/list")
def list_skills_legacy(project_id: Optional[int] = None):
    """兼容旧前端调用 GET /api/skills/list"""
    return list_skills(project_id=project_id)


@router.get("/{skill_id}")
def get_skill(skill_id: str):
    """查询单个技能"""
    data = load_skills()
    for item in data:
        if item["id"] == skill_id:
            return item
    raise HTTPException(status_code=404, detail="Skill not found")


@router.post("")
def create_skill(req: SkillCreate):
    """创建新技能（自动写入 workspace/skills/{id}/SKILL.md）"""
    data = load_skills()
    if any(d["id"] == req.id and d.get("project_id") == req.project_id for d in data):
        raise HTTPException(status_code=400, detail="Skill ID 已存在")

    skill_dir = os.path.join(SKILL_HUB_DIR, req.id)
    _write_skill_markdown(
        skill_dir=skill_dir,
        name=req.name,
        description=req.description,
        content=req.content,
    )

    entry = {
        "id": req.id,
        "name": req.name,
        "description": req.description,
        "content": req.content,
        "type": req.type,
        "project_id": req.project_id,
        "source": req.source,
        "installation_time": datetime.now().strftime("%Y年%m月%d日"),
        "status": req.status,
        "file_path": skill_dir,
        "is_builtin": False,
    }
    data.append(entry)
    _save_data(data)
    return entry


@router.put("/{skill_id}")
def update_skill(skill_id: str, req: SkillUpdate):
    """更新技能（同时同步 SKILL.md 文件）"""
    data = load_skills()
    for i, item in enumerate(data):
        if item["id"] == skill_id:
            if item.get("is_builtin"):
                raise HTTPException(status_code=400, detail="内置技能不可编辑")
            update = req.model_dump(exclude_unset=True)
            data[i].update(update)
            # 同步 SKILL.md
            if data[i].get("file_path") and (update.get("content") or update.get("name")):
                _write_skill_markdown(
                    skill_dir=data[i]["file_path"],
                    name=update.get("name") or data[i].get("name", "skill"),
                    description=update.get("description"),
                    content=update.get("content") or data[i].get("content", ""),
                )
            _save_data(data)
            return data[i]
    raise HTTPException(status_code=404, detail="Skill not found")


@router.delete("/{skill_id}")
def delete_skill(skill_id: str):
    """删除技能（同时删除 workspace 下的文件夹）"""
    data = load_skills()
    target = next((d for d in data if d["id"] == skill_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Skill not found")
    if target.get("is_builtin"):
        raise HTTPException(status_code=400, detail="内置技能不可删除")
    # 删除文件夹
    fp = target.get("file_path")
    if fp and os.path.exists(fp):
        shutil.rmtree(fp, ignore_errors=True)
    data = [d for d in data if d["id"] != skill_id]
    _save_data(data)
    return {"message": f"Skill {skill_id} deleted"}


@router.post("/upload")
def upload_skill(file_content: str = Form(...), skill_id: str = Form(...), project_id: Optional[int] = Form(None)):
    """上传 SKILL.md 内容，创建技能"""
    from fastapi import UploadFile, Form as FastAPIForm
    # 此端点主要用于前端文本粘贴创建，非文件上传
    data = load_skills()
    if any(d["id"] == skill_id for d in data):
        raise HTTPException(status_code=400, detail="Skill ID 已存在")
    safe_id = _safe_dir_name(skill_id)
    final_id = f"{safe_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    skill_dir = os.path.join(SKILL_HUB_DIR, final_id)
    # 从内容提取 frontmatter
    info = _parse_skill_md_from_string(file_content)
    name = info.get("name") or final_id
    _write_skill_markdown(skill_dir, name, info.get("description"), info.get("content"))
    entry = {
        "id": final_id,
        "name": name,
        "description": info.get("description"),
        "content": info.get("content"),
        "type": "agentskill",
        "project_id": project_id,
        "source": SOURCE_UPLOADED_FILE,
        "installation_time": datetime.now().strftime("%Y年%m月%d日"),
        "status": _STATUS_SAFE,
        "file_path": skill_dir,
        "is_builtin": False,
    }
    data.append(entry)
    _save_data(data)
    return entry


def _parse_skill_md_from_string(content: str) -> dict:
    """从字符串解析 SKILL.md frontmatter"""
    if not content.startswith("---"):
        return {"name": None, "description": None, "content": content}
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {"name": None, "description": None, "content": content}
    import yaml
    try:
        meta = yaml.safe_load(parts[1]) or {}
        body = parts[2].strip()
    except Exception:
        return {"name": None, "description": None, "content": content}
    return {"name": meta.get("name"), "description": meta.get("description"), "content": body}
