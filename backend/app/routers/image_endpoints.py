# -*- coding: utf-8 -*-
"""
AI 创作 · 图像端点 API

  GET/POST/PATCH/DELETE  /api/image/endpoints[/{key}]   端点池 CRUD（密钥只回显掩码）
  POST  /api/image/endpoints/{key}/test                 单端点连通性自检，不触发 fallback
  GET/PUT  /api/image/bindings                          服务 → 候选端点有序链
  POST /api/image/process · GET /api/image/jobs         素材库单图即席处理

「服务绑定」与「运行时选择」是两件事：
绑定由管理员在端点页维护，运行时选择由任务创建时的 endpoint_key 覆盖，
两者都进 resolve_chain() 的同一条 fallback 链。
"""
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.deps import get_current_user
from app.models.database import get_db
from app.models.image_endpoint import IMAGE_CAPABILITIES, IMAGE_SERVICES, ImageProcessJob
from app.models.user import User
from app.services import image_endpoints, image_gateway, image_process

router = APIRouter(prefix="/api/image", tags=["image-endpoints"])


class EndpointPayload(BaseModel):
    key: Optional[str] = None
    name: str = ""
    protocol: str = "webhook"
    base_url: str = ""
    model: str = ""
    auth_mode: str = "none"
    api_key_env: str = ""
    api_key_inline: str = ""
    capabilities: List[str] = Field(default_factory=list)
    params: dict = Field(default_factory=dict)
    max_refs: int = 4
    timeout_s: int = 60
    enabled: bool = True
    priority: int = 100
    note: str = ""


class BindingPayload(BaseModel):
    service: str
    capability: str = ""
    keys: List[str] = Field(default_factory=list)


class ProcessPayload(BaseModel):
    asset_id: int
    operation: str
    endpoint_key: Optional[str] = None
    params: dict = Field(default_factory=dict)


@router.get("/endpoints")
def get_endpoints(db: DBSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """端点页数据：端点池（脱敏）+ 能力/协议/服务字典 + 绑定矩阵"""
    return image_endpoints.describe(db)


@router.post("/endpoints")
def create_endpoint(payload: EndpointPayload, db: DBSession = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    item = image_endpoints.save_endpoint(db, payload.model_dump(), creating=True)
    return {"item": item, **image_endpoints.describe(db)}


@router.patch("/endpoints/{key}")
def update_endpoint(key: str, payload: EndpointPayload, db: DBSession = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    body = payload.model_dump()
    body["key"] = key
    item = image_endpoints.save_endpoint(db, body, creating=False)
    return {"item": item, **image_endpoints.describe(db)}


@router.delete("/endpoints/{key}")
def delete_endpoint(key: str, db: DBSession = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    image_endpoints.delete_endpoint(db, key)
    return {"deleted": key, **image_endpoints.describe(db)}


@router.post("/endpoints/{key}/test")
def test_endpoint(key: str, db: DBSession = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    """只试这一个端点（single=True），失败也不落到别的端点，方便定位配置问题。"""
    from app.models.image_endpoint import ImageEndpoint
    row = db.get(ImageEndpoint, key)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": 41011, "message": f"端点 {key} 不存在"})
    if row.protocol == "mock":
        return {"ok": True, "skipped": True, "detail": "内置兜底端点，无需连通性测试", "key": key}
    if not row.to_dict()["secret_ready"]:
        return {
            "ok": False,
            "detail": f"密钥未就绪：{row.secret_source()}，请在 .env 配置或改用 inline / none",
            "key": key,
        }
    result = image_gateway.process_image(
        service="adhoc",
        capability=(row.capabilities or ["txt2img"])[0],
        prompt="连通性自检，输出一张极简测试图",
        refs=[],
        params={"size": "256x256"},
        preferred_key=key,
        single=True,
        db=db,
    )
    return {
        "ok": not result.is_mock,
        "key": key,
        "latency_ms": result.latency_ms,
        "detail": "端点返回了可解码的图片" if not result.is_mock else result.reason,
        "attempts": result.attempts,
        **({"bytes": len(result.image)} if result.image else {}),
    }


@router.get("/bindings")
def get_bindings(db: DBSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return {"items": image_endpoints.list_bindings(db), "services": IMAGE_SERVICES}


@router.put("/bindings")
def put_bindings(payload: BindingPayload, db: DBSession = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    items = image_endpoints.set_bindings(db, payload.service, payload.keys, payload.capability)
    return {"items": items, **image_endpoints.describe(db)}


@router.post("/process")
def process_asset(payload: ProcessPayload, background: BackgroundTasks,
                  db: DBSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """对素材库里的一张图立即处理；异步执行，前端轮询 /api/image/jobs"""
    job = image_process.create_job(
        db,
        asset_id=payload.asset_id,
        operation=payload.operation,
        endpoint_key=payload.endpoint_key,
        params=payload.params,
        owner_id=getattr(current_user, "id", None),
    )
    background.add_task(image_process.run_job, job.id)
    return {"item": job.to_dict(), "queued": True}


@router.get("/jobs")
def list_jobs(
    asset_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(ImageProcessJob)
    if asset_id is not None:
        query = query.filter(ImageProcessJob.asset_id == asset_id)
    total = query.count()
    rows = (
        query.order_by(ImageProcessJob.created_at.desc(), ImageProcessJob.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"items": [row.to_dict() for row in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/operations")
def get_operations():
    """能力标签字典，供即席处理弹窗渲染"""
    return {"items": [{"key": k, "label": v} for k, v in IMAGE_CAPABILITIES.items()]}
