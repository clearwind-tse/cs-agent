# -*- coding: utf-8 -*-
"""
SFT/DPO 训练数据管理 API

提供训练数据导出、标注、管理接口
支持 SFT（监督微调）和 DPO（直接偏好优化）两阶段训练路径
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session as DBSession
from typing import List, Optional
from pydantic import BaseModel
import json
from datetime import datetime

from app.models.database import get_db
from app.models.dpo import DpoPreferencePair, SftTrainingSample, TrainingJob, AnnotationStatus
from app.services.sft_service import sft_service
from app.services.dpo_service import dpo_service

router = APIRouter(prefix="/api/training", tags=["training"])


# ==================== 请求模型 ====================

class SftSampleRequest(BaseModel):
    """SFT 样本请求"""
    category: Optional[str] = None
    is_approved: bool = True
    limit: int = 100
    offset: int = 0


class DpoPairRequest(BaseModel):
    """DPO 偏好对请求"""
    category: Optional[str] = None
    status: Optional[str] = None
    limit: int = 100
    offset: int = 0


class AnnotateRequest(BaseModel):
    """标注请求"""
    chosen_index: int
    annotated_by: str
    notes: Optional[str] = None


class GenerateRequest(BaseModel):
    """生成请求"""
    min_quality: str = "medium"
    max_pairs: int = 500
    # 每个业务问题生成几条不同类型的 rejected（1 chosen × N rejected）
    rejected_per_pair: int = 3


class ExportRequest(BaseModel):
    """导出请求"""
    format: str = "sharegpt"  # sharegpt, alpaca, openai, dpo
    categories: Optional[List[str]] = None


class TrainingJobRequest(BaseModel):
    """训练任务请求"""
    job_type: str  # sft, dpo
    job_name: str
    base_model: Optional[str] = None
    dataset_id: Optional[str] = None
    config: Optional[dict] = None


# ==================== SFT 训练数据接口 ====================

@router.get("/sft/samples")
def list_sft_samples(
    category: Optional[str] = None,
    is_approved: bool = True,
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    db: DBSession = Depends(get_db)
):
    """
    获取 SFT 训练样本列表
    
    - **category**: 按业务分类筛选
    - **is_approved**: 是否只返回已审核的样本
    - **limit/offset**: 分页参数
    """
    return sft_service.get_samples(
        category=category,
        is_approved=is_approved,
        limit=limit,
        offset=offset
    )


@router.post("/sft/extract")
def extract_sft_samples(
    session_id: Optional[str] = None,
    min_quality: str = Query("medium", pattern="^(high|medium|low)$"),
    max_samples: int = Query(1000, le=10000),
    db: DBSession = Depends(get_db)
):
    """
    从聊天记录提取 SFT 训练样本
    
    - **session_id**: 指定会话ID，不填则处理全部
    - **min_quality**: 最低质量等级
    - **max_samples**: 最大样本数
    
    返回：提取的样本数
    """
    samples = sft_service.extract_from_chats(
        session_id=session_id,
        min_quality=min_quality,
        max_samples=max_samples
    )
    
    count = sft_service.save_samples(samples)
    
    return {
        "extracted": len(samples),
        "saved": count,
        "message": f"成功提取并保存 {count} 条 SFT 样本"
    }


@router.post("/sft/export")
def export_sft_data(
    export_req: ExportRequest,
    db: DBSession = Depends(get_db)
):
    """
    导出 SFT 训练数据
    
    支持的格式：
    - **sharegpt**: 多轮对话格式（推荐）
    - **alpaca**: 指令微调格式
    - **openai**: OpenAI Chat 格式
    """
    if export_req.format not in ["sharegpt", "alpaca", "openai"]:
        raise HTTPException(status_code=400, detail=f"不支持的格式: {export_req.format}")
    
    data = sft_service.export_for_training(
        format=export_req.format,
        categories=export_req.categories
    )
    
    return {
        "format": export_req.format,
        "count": len(data),
        "data": data
    }


# ==================== DPO 偏好对接口 ====================

@router.get("/dpo/pairs")
def list_dpo_pairs(
    category: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    db: DBSession = Depends(get_db)
):
    """
    获取 DPO 偏好对列表
    
    - **category**: 按业务分类筛选
    - **status**: 按标注状态筛选 (pending/annotated/reviewed)
    """
    return dpo_service.get_pairs(
        category=category,
        status=status,
        limit=limit,
        offset=offset
    )


@router.get("/dpo/pairs/{pair_id}")
def get_dpo_pair_detail(
    pair_id: str,
    db: DBSession = Depends(get_db)
):
    """
    获取单个偏好对详情
    
    返回完整的 prompt、chosen/rejected 回复及标注信息
    """
    detail = dpo_service.get_pair_detail(pair_id)
    
    if not detail:
        raise HTTPException(status_code=404, detail="偏好对不存在")
    
    return detail


@router.post("/dpo/generate")
def generate_dpo_pairs(
    generate_req: GenerateRequest,
    db: DBSession = Depends(get_db)
):
    """
    生成 DPO 偏好对
    
    从 SFT 样本自动生成包含 chosen/rejected 的偏好对：
    - chosen: 高质量回复（来自 SFT 模型）
    - rejected: 低质量回复（模拟算错运费、态度生硬等）
    """
    pairs = dpo_service.generate_preference_pairs(
        min_quality=generate_req.min_quality,
        max_pairs=generate_req.max_pairs,
        rejected_per_pair=generate_req.rejected_per_pair
    )
    
    count = dpo_service.save_pairs(pairs)
    
    return {
        "generated": len(pairs),
        "saved": count,
        "message": f"成功生成 {count} 条 DPO 偏好对"
    }


@router.post("/dpo/pairs/{pair_id}/annotate")
def annotate_dpo_pair(
    pair_id: str,
    annotate_req: AnnotateRequest,
    db: DBSession = Depends(get_db)
):
    """
    标注偏好对
    
    业务主管对候选回复进行标注：
    - **chosen_index**: 选中的最优回复索引（0-based）
    - **annotated_by**: 标注人姓名
    - **notes**: 标注备注（可选）
    """
    success = dpo_service.annotate_pair(
        pair_id=pair_id,
        chosen_index=annotate_req.chosen_index,
        annotated_by=annotate_req.annotated_by,
        notes=annotate_req.notes
    )
    
    if not success:
        raise HTTPException(status_code=404, detail="偏好对不存在")
    
    return {"message": "标注成功"}


@router.post("/dpo/export")
def export_dpo_data(
    export_req: ExportRequest,
    db: DBSession = Depends(get_db)
):
    """
    导出 DPO 训练数据
    
    格式：prompt + chosen + rejected 偏好对
    适用于 OpenAI DPO、TRL、langchain 等框架
    """
    data = dpo_service.export_for_training(format=export_req.format)
    
    return {
        "format": export_req.format,
        "count": len(data),
        "data": data
    }


@router.get("/dpo/statistics")
def get_dpo_statistics(
    db: DBSession = Depends(get_db)
):
    """获取 DPO 数据统计"""
    stats = dpo_service.get_statistics()
    return stats


# ==================== 训练任务接口 ====================

@router.post("/jobs")
def create_training_job(
    job_req: TrainingJobRequest,
    db: DBSession = Depends(get_db)
):
    """
    创建训练任务
    
    - **job_type**: 任务类型 (sft/dpo)
    - **job_name**: 任务名称
    - **base_model**: 基础模型
    - **dataset_id**: 关联的数据集ID
    - **config**: 训练配置参数
    """
    job = TrainingJob(
        job_type=job_req.job_type,
        job_name=job_req.job_name,
        base_model=job_req.base_model,
        dataset_id=job_req.dataset_id,
        config_json=job_req.config,
        status="pending",
        created_by="system"
    )
    
    db.add(job)
    db.commit()
    db.refresh(job)
    
    return {
        "id": job.id,
        "job_type": job.job_type,
        "job_name": job.job_name,
        "status": job.status,
        "created_at": job.created_at.isoformat() if job.created_at else None
    }


@router.get("/jobs")
def list_training_jobs(
    job_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(50, le=100),
    db: DBSession = Depends(get_db)
):
    """
    获取训练任务列表
    
    - **job_type**: 按任务类型筛选
    - **status**: 按状态筛选
    """
    query = db.query(TrainingJob)
    
    if job_type:
        query = query.filter(TrainingJob.job_type == job_type)
    
    if status:
        query = query.filter(TrainingJob.status == status)
    
    jobs = query.order_by(
        TrainingJob.created_at.desc()
    ).limit(limit).all()
    
    return {
        "total": len(jobs),
        "jobs": [
            {
                "id": j.id,
                "job_type": j.job_type,
                "job_name": j.job_name,
                "base_model": j.base_model,
                "status": j.status,
                "progress": j.progress,
                "created_at": j.created_at.isoformat() if j.created_at else None
            }
            for j in jobs
        ]
    }


@router.get("/jobs/{job_id}")
def get_training_job(
    job_id: str,
    db: DBSession = Depends(get_db)
):
    """获取单个训练任务详情"""
    job = db.query(TrainingJob).filter(TrainingJob.id == job_id).first()
    
    if not job:
        raise HTTPException(status_code=404, detail="训练任务不存在")
    
    return {
        "id": job.id,
        "job_type": job.job_type,
        "job_name": job.job_name,
        "base_model": job.base_model,
        "dataset_id": job.dataset_id,
        "config": job.config_json,
        "status": job.status,
        "progress": job.progress,
        "logs": job.logs,
        "metrics": job.metrics_json,
        "model_path": job.model_path,
        "created_by": job.created_by,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None
    }


@router.put("/jobs/{job_id}/status")
def update_training_job_status(
    job_id: str,
    status: str,
    progress: Optional[float] = None,
    db: DBSession = Depends(get_db)
):
    """更新训练任务状态"""
    job = db.query(TrainingJob).filter(TrainingJob.id == job_id).first()
    
    if not job:
        raise HTTPException(status_code=404, detail="训练任务不存在")
    
    job.status = status
    
    if progress is not None:
        job.progress = progress
    
    if status == "running" and not job.started_at:
        from datetime import datetime
        job.started_at = datetime.utcnow()
    
    db.commit()
    
    return {"message": "状态更新成功", "status": job.status}


@router.put("/jobs/{job_id}/complete")
def complete_training_job(
    job_id: str,
    metrics: dict,
    model_path: Optional[str] = None,
    db: DBSession = Depends(get_db)
):
    """标记训练任务完成"""
    job = db.query(TrainingJob).filter(TrainingJob.id == job_id).first()
    
    if not job:
        raise HTTPException(status_code=404, detail="训练任务不存在")
    
    job.status = "success"
    job.metrics_json = metrics
    job.progress = 100.0
    
    if model_path:
        job.model_path = model_path
    
    from datetime import datetime
    job.completed_at = datetime.utcnow()
    
    db.commit()
    
    return {
        "message": "训练任务已完成",
        "metrics": metrics,
        "model_path": model_path
    }


# ==================== 数据统计接口 ====================

@router.get("/statistics")
def get_training_statistics(
    db: DBSession = Depends(get_db)
):
    """获取训练数据统计概览"""
    # SFT 样本统计
    sft_total = db.query(SftTrainingSample).count()
    sft_approved = db.query(SftTrainingSample).filter(
        SftTrainingSample.is_approved == True
    ).count()

    # DPO 偏好对统计
    dpo_stats = dpo_service.get_statistics()

    # 训练任务统计
    job_total = db.query(TrainingJob).count()
    job_completed = db.query(TrainingJob).filter(
        TrainingJob.status == "success"
    ).count()

    return {
        "sft_samples": {
            "total": sft_total,
            "approved": sft_approved
        },
        "dpo_pairs": dpo_stats,
        "training_jobs": {
            "total": job_total,
            "completed": job_completed
        }
    }
