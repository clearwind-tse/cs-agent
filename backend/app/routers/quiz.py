# -*- coding: utf-8 -*-
"""
AI 考核 API
出题 → 答题 → AI评判 → 人工评测
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import desc, func
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from app.models.database import get_db
from app.models.chat import Quiz, QuizAttempt
from app.services.quiz import generate_quiz_questions, ai_grade_answers
from app.services.xiaocan_persona import CATEGORY_LABELS

router = APIRouter(prefix="/api/quiz", tags=["quiz"])


# ==================== 请求/响应模型 ====================

class GenerateQuizRequest(BaseModel):
    category: str = Field("savings_explain", description="考核分类")
    count: int = Field(10, ge=1, le=20, description="题目数量")
    title: Optional[str] = Field(None, description="试卷标题（可选）")


class SubmitAnswersRequest(BaseModel):
    answers: List[dict] = Field(..., description="[{question_id, answer}]")


class HumanReviewRequest(BaseModel):
    human_score: float = Field(..., ge=0, le=100, description="人工总分 0-100")
    human_feedback: str = Field("", description="人工评语")


# ==================== API 端点 ====================

@router.post("/generate")
def generate_quiz(req: GenerateQuizRequest, db: DBSession = Depends(get_db)):
    """AI 生成考核试卷"""
    try:
        questions = generate_quiz_questions(db, category=req.category, count=req.count)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"出题失败: {str(e)}")

    cat_labels = CATEGORY_LABELS
    title = req.title or f"{cat_labels.get(req.category, '小蚕客服')}\u8003\u6838 #{db.query(func.count(Quiz.id)).scalar() + 1}"

    quiz = Quiz(
        title=title,
        category=req.category,
        questions_json=questions,
        question_count=len(questions),
        status="generated",
    )
    db.add(quiz)
    db.commit()
    db.refresh(quiz)

    return {
        "id": quiz.id,
        "title": quiz.title,
        "category": quiz.category,
        "question_count": quiz.question_count,
        "questions": questions,
    }


@router.get("/list")
def list_quizzes(
    category: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: DBSession = Depends(get_db),
):
    """获取考核列表"""
    q = db.query(Quiz)
    if category:
        q = q.filter(Quiz.category == category)
    total = q.count()
    items = q.order_by(desc(Quiz.created_at)).offset(skip).limit(limit).all()

    result = []
    for quiz in items:
        attempt_count = db.query(func.count(QuizAttempt.id)).filter(
            QuizAttempt.quiz_id == quiz.id
        ).scalar()
        result.append({
            "id": quiz.id,
            "title": quiz.title,
            "category": quiz.category,
            "question_count": quiz.question_count,
            "status": quiz.status,
            "attempt_count": attempt_count,
            "created_at": quiz.created_at.isoformat() if quiz.created_at else None,
        })

    return {"total": total, "items": result}


@router.get("/{quiz_id}")
def get_quiz(quiz_id: int, db: DBSession = Depends(get_db)):
    """获取试卷详情（含题目）"""
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="试卷不存在")

    return {
        "id": quiz.id,
        "title": quiz.title,
        "category": quiz.category,
        "question_count": quiz.question_count,
        "questions": quiz.questions_json,
        "status": quiz.status,
        "created_at": quiz.created_at.isoformat() if quiz.created_at else None,
    }


@router.delete("/{quiz_id}")
def delete_quiz(quiz_id: int, db: DBSession = Depends(get_db)):
    """删除试卷及其所有作答记录"""
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="试卷不存在")

    db.query(QuizAttempt).filter(QuizAttempt.quiz_id == quiz_id).delete()
    db.delete(quiz)
    db.commit()

    return {"message": "删除成功", "id": quiz_id}


@router.post("/{quiz_id}/start")
def start_attempt(quiz_id: int, db: DBSession = Depends(get_db)):
    """开始作答 - 创建一条作答记录"""
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="试卷不存在")

    attempt = QuizAttempt(
        quiz_id=quiz_id,
        status="answering",
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    return {
        "attempt_id": attempt.id,
        "quiz_id": quiz_id,
        "status": "answering",
    }


@router.post("/attempt/{attempt_id}/submit")
def submit_answers(
    attempt_id: int,
    req: SubmitAnswersRequest,
    db: DBSession = Depends(get_db),
):
    """提交答案"""
    attempt = db.query(QuizAttempt).filter(QuizAttempt.id == attempt_id).first()
    if not attempt:
        raise HTTPException(status_code=404, detail="作答记录不存在")
    if attempt.status not in ("answering",):
        raise HTTPException(status_code=400, detail="当前状态不允许提交答案")

    attempt.user_answers_json = req.answers
    attempt.status = "submitted"
    attempt.submitted_at = datetime.utcnow()
    db.commit()

    return {"message": "答案已提交", "attempt_id": attempt_id, "status": "submitted"}


@router.post("/attempt/{attempt_id}/ai-grade")
def ai_grade(attempt_id: int, db: DBSession = Depends(get_db)):
    """AI 评判答案"""
    attempt = db.query(QuizAttempt).filter(QuizAttempt.id == attempt_id).first()
    if not attempt:
        raise HTTPException(status_code=404, detail="作答记录不存在")
    if attempt.status not in ("submitted",):
        raise HTTPException(status_code=400, detail="请先提交答案")

    quiz = db.query(Quiz).filter(Quiz.id == attempt.quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="试卷不存在")

    try:
        evaluations = ai_grade_answers(quiz.questions_json, attempt.user_answers_json)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 评判失败: {str(e)}")

    scores = [e.get("score", 0) for e in evaluations]
    total = round(sum(scores) / len(scores) * 10, 1) if scores else 0

    attempt.ai_evaluation_json = evaluations
    attempt.ai_total_score = total
    attempt.status = "ai_graded"
    attempt.graded_at = datetime.utcnow()
    db.commit()

    return {
        "attempt_id": attempt_id,
        "evaluations": evaluations,
        "ai_total_score": total,
        "status": "ai_graded",
    }


@router.put("/attempt/{attempt_id}/human-review")
def human_review(
    attempt_id: int,
    req: HumanReviewRequest,
    db: DBSession = Depends(get_db),
):
    """人工评测"""
    attempt = db.query(QuizAttempt).filter(QuizAttempt.id == attempt_id).first()
    if not attempt:
        raise HTTPException(status_code=404, detail="作答记录不存在")

    attempt.human_score = req.human_score
    attempt.human_feedback = req.human_feedback
    attempt.status = "human_reviewed"
    db.commit()

    return {
        "attempt_id": attempt_id,
        "human_score": req.human_score,
        "status": "human_reviewed",
    }


@router.get("/attempt/{attempt_id}")
def get_attempt(attempt_id: int, db: DBSession = Depends(get_db)):
    """获取作答详情"""
    attempt = db.query(QuizAttempt).filter(QuizAttempt.id == attempt_id).first()
    if not attempt:
        raise HTTPException(status_code=404, detail="作答记录不存在")

    quiz = db.query(Quiz).filter(Quiz.id == attempt.quiz_id).first()

    return {
        "id": attempt.id,
        "quiz_id": attempt.quiz_id,
        "quiz_title": quiz.title if quiz else None,
        "questions": quiz.questions_json if quiz else [],
        "user_answers": attempt.user_answers_json,
        "ai_evaluation": attempt.ai_evaluation_json,
        "ai_total_score": attempt.ai_total_score,
        "human_score": attempt.human_score,
        "human_feedback": attempt.human_feedback,
        "status": attempt.status,
        "created_at": attempt.created_at.isoformat() if attempt.created_at else None,
        "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
        "graded_at": attempt.graded_at.isoformat() if attempt.graded_at else None,
    }


@router.get("/attempts/list")
def list_attempts(
    quiz_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: DBSession = Depends(get_db),
):
    """获取所有作答记录"""
    q = db.query(QuizAttempt)
    if quiz_id:
        q = q.filter(QuizAttempt.quiz_id == quiz_id)
    if status:
        q = q.filter(QuizAttempt.status == status)

    total = q.count()
    items = q.order_by(desc(QuizAttempt.created_at)).offset(skip).limit(limit).all()

    result = []
    for attempt in items:
        quiz = db.query(Quiz).filter(Quiz.id == attempt.quiz_id).first()
        result.append({
            "id": attempt.id,
            "quiz_id": attempt.quiz_id,
            "quiz_title": quiz.title if quiz else "未知试卷",
            "quiz_category": quiz.category if quiz else None,
            "ai_total_score": attempt.ai_total_score,
            "human_score": attempt.human_score,
            "status": attempt.status,
            "created_at": attempt.created_at.isoformat() if attempt.created_at else None,
            "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
        })

    return {"total": total, "items": result}
