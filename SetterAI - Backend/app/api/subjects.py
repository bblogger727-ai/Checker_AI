"""
Subjects API - Manage CA subjects with syllabus and marking schemes.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from app.core.database import get_db
from app.models import Subject

router = APIRouter(prefix="/api/setter/subjects", tags=["Subjects"])


class SubjectCreate(BaseModel):
    name: str
    code: str
    level: Optional[str] = None
    syllabus_json: Optional[dict] = None
    marking_scheme_json: Optional[dict] = None


class SubjectResponse(BaseModel):
    id: int
    name: str
    code: str
    level: Optional[str]
    syllabus_json: Optional[dict]
    marking_scheme_json: Optional[dict]
    question_count: int = 0
    template_count: int = 0
    
    class Config:
        from_attributes = True


@router.get("", response_model=List[SubjectResponse])
def list_subjects(db: Session = Depends(get_db)):
    """List all subjects."""
    subjects = db.query(Subject).order_by(Subject.name).all()
    return [SubjectResponse(
        id=s.id,
        name=s.name,
        code=s.code,
        level=s.level,
        syllabus_json=s.syllabus_json,
        marking_scheme_json=s.marking_scheme_json,
        question_count=len(s.questions),
        template_count=len(s.templates)
    ) for s in subjects]


@router.post("", response_model=SubjectResponse)
def create_subject(data: SubjectCreate, db: Session = Depends(get_db)):
    """Create a new subject."""
    # Check if code exists
    existing = db.query(Subject).filter(Subject.code == data.code).first()
    if existing:
        raise HTTPException(status_code=400, detail="Subject code already exists")
    
    subject = Subject(
        name=data.name,
        code=data.code,
        level=data.level,
        syllabus_json=data.syllabus_json,
        marking_scheme_json=data.marking_scheme_json
    )
    db.add(subject)
    db.commit()
    db.refresh(subject)
    
    return SubjectResponse(
        id=subject.id,
        name=subject.name,
        code=subject.code,
        level=subject.level,
        syllabus_json=subject.syllabus_json,
        marking_scheme_json=subject.marking_scheme_json,
        question_count=0,
        template_count=0
    )


@router.get("/{subject_id}", response_model=SubjectResponse)
def get_subject(subject_id: int, db: Session = Depends(get_db)):
    """Get subject details."""
    subject = db.query(Subject).filter(Subject.id == subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")
    
    return SubjectResponse(
        id=subject.id,
        name=subject.name,
        code=subject.code,
        level=subject.level,
        syllabus_json=subject.syllabus_json,
        marking_scheme_json=subject.marking_scheme_json,
        question_count=len(subject.questions),
        template_count=len(subject.templates)
    )


@router.put("/{subject_id}", response_model=SubjectResponse)
def update_subject(subject_id: int, data: SubjectCreate, db: Session = Depends(get_db)):
    """Update subject details."""
    subject = db.query(Subject).filter(Subject.id == subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")
    
    subject.name = data.name
    subject.code = data.code
    subject.level = data.level
    if data.syllabus_json:
        subject.syllabus_json = data.syllabus_json
    if data.marking_scheme_json:
        subject.marking_scheme_json = data.marking_scheme_json
    subject.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(subject)
    
    return SubjectResponse(
        id=subject.id,
        name=subject.name,
        code=subject.code,
        level=subject.level,
        syllabus_json=subject.syllabus_json,
        marking_scheme_json=subject.marking_scheme_json,
        question_count=len(subject.questions),
        template_count=len(subject.templates)
    )


@router.delete("/{subject_id}")
def delete_subject(subject_id: int, db: Session = Depends(get_db)):
    """Delete a subject."""
    subject = db.query(Subject).filter(Subject.id == subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")
    
    db.delete(subject)
    db.commit()
    return {"status": "deleted"}
