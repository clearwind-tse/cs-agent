# -*- coding: utf-8 -*-
"""
AI 创作任务路由（两阶段生成）

  POST   /api/studio/tasks              建任务 → 同步产出「规划」，停在 planned 等人确认
  GET    /api/studio/tasks              任务列表
  GET    /api/studio/tasks/{id}          单条（前端轮询进度）
  POST   /api/studio/tasks/{id}/confirm  确认规划 → 后台执行出图（BackgroundTasks）
  POST   /api/studio/tasks/{id}/cancel   取消未开始的任务
  POST   /api/studio/tasks/{id}/retry    失败后重跑（回到 generating，规划保留）
  GET    /api/studio/engine             当前引擎信息，前端据此显式标注 mock

执行放在 BackgroundTasks：出图是秒级到分钟级操作，同步请求会被网关掐断；
进度写在 studio_tasks.progress，前端轮询单条任务即可，不需要 WebSocket。

BackgroundTasks 是进程内的：进程被 kill / uvicorn reload / 机器重启时不会有任何回调，
任务会永远停在 generating。所以每个读/写任务的入口都先跑一次 stale sweep，
把超时未推进的任务标成 failed，用户点「重跑」即可恢复，不用手动改库。
"""
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.deps import get_current_user
from app.models.database import get_db
from app.models.studio_task import StudioTask
from app.models.user import User
from app.services import studio_task_service as tasks

router = APIRouter(prefix="/api/studio", tags=["studio"])


class TaskCreateRequest(BaseModel):
    kind: str = Field(..., description="set/style/sku/outfit/retouch")
    asset_ids: List[int] = Field(default_factory=list, description="输入素材 id（由 config.slots 汇总，服务端会重算）")
    count: int = Field(4, ge=1, le=8, description="出图张数；不同功能语义不同，见 studioKinds.ts")
    ratio: str = Field("1:1", description="1:1 / 3:4 / 4:3 / 16:9")
    note: Optional[str] = Field(None, description="补充要求，会拼进每张的 prompt")
    config: dict = Field(
        default_factory=dict,
        description="功能专属配置：{slots: {角色: [素材 id]}, fields: {选项 key: 值}}；key 白名单见 studio_task_service.KIND_CONFIG",
    )
    endpoint_key: Optional[str] = Field(
        None, description="本次任务指定用哪个图像端点；留空 = 按服务绑定链自动挑，仍保留 fallback",
    )
    endpoint_params: dict = Field(
        default_factory=dict, description="传给图像端点的额外参数（size / strength / seed / extra…）",
    )


def _sweep(db: DBSession) -> None:
    """读/写任务前收掉僵尸 generating；自愈失败不能让主接口 500"""
    try:
        tasks.sweep_stale_tasks(db)
    except Exception as exc:  # pragma: no cover
        print(f"[WARN] studio stale sweep failed: {exc}")


@router.get("/engine")
def get_engine(db: DBSession = Depends(get_db)):
    """引擎说明：前端必须把「有没有真实端点」展示出来，不能让人误以为这是真出图"""
    return tasks.engine_info(db)


@router.post("/tasks")
def create_task(
    payload: TaskCreateRequest,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = tasks.create_task(db, payload.kind, payload.model_dump(), getattr(current_user, "id", None))
    return {"item": task.to_dict()}


@router.get("/tasks")
def list_tasks(
    kind: Optional[str] = Query(None),
    task_status: Optional[str] = Query(None, alias="status", description="按状态过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _sweep(db)
    query = db.query(StudioTask)
    if kind:
        query = query.filter(StudioTask.kind == kind)
    if task_status:
        query = query.filter(StudioTask.status == task_status)

    total = query.count()
    rows = (
        query.order_by(StudioTask.created_at.desc(), StudioTask.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": [row.to_dict() for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/tasks/{task_id}")
def get_task(
    task_id: int,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _sweep(db)
    task = db.get(StudioTask, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": 40410, "message": "任务不存在"})
    return {"item": task.to_dict()}


@router.post("/tasks/{task_id}/confirm")
def confirm_task(
    task_id: int,
    background: BackgroundTasks,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """两阶段的闸门：不点这一下，永远不会触发后台执行"""
    _sweep(db)
    task = db.get(StudioTask, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": 40410, "message": "任务不存在"})

    if task.status == "generating":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": 40910, "message": "任务正在执行"})
    if task.status in ("done", "cancelled"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": 40911, "message": f"任务已{task.status}，不能重复确认"},
        )
    if task.status not in ("planned", "failed"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": 40912, "message": "任务状态异常，请重建"})

    shots = (task.plan or {}).get("shots") or []
    if not shots:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": 40012, "message": "没有可执行的规划"})

    # 先落一个「generating」避免前端连点重复提交，再交给后台
    task.status = "generating"
    task.error = None
    task.done_shots = 0
    task.progress = 0
    task.outputs = None
    db.commit()

    background.add_task(tasks.run_generation, task.id)
    return {"item": task.to_dict(), "queued": True}


@router.post("/tasks/{task_id}/cancel")
def cancel_task(
    task_id: int,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _sweep(db)
    task = db.get(StudioTask, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": 40410, "message": "任务不存在"})
    if task.status not in ("planned", "failed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": 40913, "message": "只有待确认 / 失败的任务可以取消"},
        )
    task.status = "cancelled"
    db.commit()
    return {"item": task.to_dict()}


@router.post("/tasks/{task_id}/retry")
def retry_task(
    task_id: int,
    background: BackgroundTasks,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """失败后重跑：规划保留，直接重新执行（僵尸任务自愈后也走这里）"""
    _sweep(db)
    task = db.get(StudioTask, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": 40410, "message": "任务不存在"})
    if task.status != "failed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": 40914, "message": "只有失败的任务可以重跑"})

    task.status = "generating"
    task.error = None
    task.done_shots = 0
    task.progress = 0
    task.outputs = None
    task.finished_at = None
    db.commit()

    background.add_task(tasks.run_generation, task.id)
    return {"item": task.to_dict(), "queued": True}
