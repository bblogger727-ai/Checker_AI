"""
Question Bank API - Manage questions for paper generation.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from app.core.database import get_db
from app.models import QuestionBank, Subject

router = APIRouter(prefix="/api/setter/questions", tags=["Question Bank"])


class QuestionCreate(BaseModel):
    subject_id: int
    question_text: str
    question_type: str  # "MCQ", "Descriptive", "Practical"
    marks: int
    topic: Optional[str] = None
    subtopic: Optional[str] = None
    difficulty: Optional[str] = "Medium"
    pyq_year: Optional[int] = None
    pyq_session: Optional[str] = None
    model_answer: Optional[str] = None
    options_json: Optional[dict] = None  # For MCQs


class QuestionResponse(BaseModel):
    id: int
    subject_id: int
    question_text: str
    question_type: str
    marks: int
    topic: Optional[str]
    subtopic: Optional[str]
    difficulty: Optional[str]
    pyq_year: Optional[int]
    pyq_session: Optional[str]
    frequency_score: float
    model_answer: Optional[str]
    options_json: Optional[dict]
    
    class Config:
        from_attributes = True


@router.get("", response_model=List[QuestionResponse])
def list_questions(
    subject_id: Optional[int] = Query(None),
    question_type: Optional[str] = Query(None),
    topic: Optional[str] = Query(None),
    difficulty: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db)
):
    """List questions with optional filters."""
    query = db.query(QuestionBank)
    
    if subject_id:
        query = query.filter(QuestionBank.subject_id == subject_id)
    if question_type:
        query = query.filter(QuestionBank.question_type == question_type)
    if topic:
        query = query.filter(QuestionBank.topic.ilike(f"%{topic}%"))
    if difficulty:
        query = query.filter(QuestionBank.difficulty == difficulty)
    
    questions = query.order_by(QuestionBank.frequency_score.desc()).limit(limit).all()
    return questions


@router.post("", response_model=QuestionResponse)
def create_question(data: QuestionCreate, db: Session = Depends(get_db)):
    """Add a question to the bank."""
    # Verify subject exists
    subject = db.query(Subject).filter(Subject.id == data.subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")
    
    question = QuestionBank(
        subject_id=data.subject_id,
        question_text=data.question_text,
        question_type=data.question_type,
        marks=data.marks,
        topic=data.topic,
        subtopic=data.subtopic,
        difficulty=data.difficulty,
        pyq_year=data.pyq_year,
        pyq_session=data.pyq_session,
        model_answer=data.model_answer,
        options_json=data.options_json,
        frequency_score=1.0 if data.pyq_year else 0.0
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    
    return question


@router.get("/{question_id}", response_model=QuestionResponse)
def get_question(question_id: int, db: Session = Depends(get_db)):
    """Get question details."""
    question = db.query(QuestionBank).filter(QuestionBank.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    return question


@router.put("/{question_id}", response_model=QuestionResponse)
def update_question(question_id: int, data: QuestionCreate, db: Session = Depends(get_db)):
    """Update a question."""
    question = db.query(QuestionBank).filter(QuestionBank.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    
    question.question_text = data.question_text
    question.question_type = data.question_type
    question.marks = data.marks
    question.topic = data.topic
    question.subtopic = data.subtopic
    question.difficulty = data.difficulty
    question.pyq_year = data.pyq_year
    question.pyq_session = data.pyq_session
    question.model_answer = data.model_answer
    question.options_json = data.options_json
    
    db.commit()
    db.refresh(question)
    return question


@router.delete("/{question_id}")
def delete_question(question_id: int, db: Session = Depends(get_db)):
    """Delete a question."""
    question = db.query(QuestionBank).filter(QuestionBank.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    
    db.delete(question)
    db.commit()
    return {"status": "deleted"}


@router.post("/bulk", response_model=dict)
def bulk_create_questions(questions: List[QuestionCreate], db: Session = Depends(get_db)):
    """Bulk add questions to the bank."""
    created = 0
    for q in questions:
        question = QuestionBank(
            subject_id=q.subject_id,
            question_text=q.question_text,
            question_type=q.question_type,
            marks=q.marks,
            topic=q.topic,
            subtopic=q.subtopic,
            difficulty=q.difficulty,
            pyq_year=q.pyq_year,
            pyq_session=q.pyq_session,
            model_answer=q.model_answer,
            options_json=q.options_json,
            frequency_score=1.0 if q.pyq_year else 0.0
        )
        db.add(question)
        created += 1
    
    db.commit()
    return {"created": created}
