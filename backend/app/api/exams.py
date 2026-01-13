"""
Exam Management API Routes (PostgreSQL + Full Debug Storage)

CRUD operations for exams with automatic schema/model answer generation.
All intermediate steps saved for debugging.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import os

from app.core.database import get_db
from app.models import Exam, StudentPaper
from app.services.solution_text_extractor import extract_solution_text
from app.services.solution_schema_builder import build_solution_schema
from app.services.model_answer_builder import build_model_answers

router = APIRouter(prefix="/api/exams", tags=["Exams"])


# Pydantic models
class ExamResponse(BaseModel):
    id: int
    name: str
    subject: Optional[str] = None
    exam_date: Optional[datetime] = None
    processing_status: str
    created_at: datetime
    student_count: int = 0
    
    class Config:
        from_attributes = True


class ExamDetailResponse(ExamResponse):
    schema_json: Optional[dict] = None
    model_answers_json: Optional[dict] = None
    solution_text: Optional[str] = None  # For debugging


class StudentSummary(BaseModel):
    id: int
    student_name: str
    roll_number: Optional[str] = None
    status: str
    obtained_marks: Optional[int] = None
    total_marks: Optional[int] = None
    percentage: Optional[int] = None
    grade: Optional[str] = None
    
    class Config:
        from_attributes = True


@router.get("", response_model=List[ExamResponse])
def list_exams(db: Session = Depends(get_db)):
    """List all exams."""
    exams = db.query(Exam).order_by(Exam.created_at.desc()).all()
    
    result = []
    for exam in exams:
        result.append(ExamResponse(
            id=exam.id,
            name=exam.name,
            subject=exam.subject,
            exam_date=exam.exam_date,
            processing_status=exam.processing_status,
            created_at=exam.created_at,
            student_count=len(exam.student_papers)
        ))
    return result


@router.post("", response_model=ExamResponse)
async def create_exam(
    name: str = Form(...),
    subject: Optional[str] = Form(None),
    exam_date: Optional[str] = Form(None),
    solution_pdf: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Create a new exam with solution PDF.
    Automatically generates question schema and model answers.
    All steps saved to database for debugging.
    """
    # Create exam directory
    os.makedirs("uploads/exams", exist_ok=True)
    
    # Save solution PDF
    pdf_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{solution_pdf.filename}"
    pdf_path = f"uploads/exams/{pdf_filename}"
    
    content = await solution_pdf.read()
    with open(pdf_path, "wb") as f:
        f.write(content)
    
    # Parse exam_date
    parsed_date = None
    if exam_date:
        try:
            parsed_date = datetime.fromisoformat(exam_date)
        except:
            pass
    
    # Create exam record
    exam = Exam(
        name=name,
        subject=subject,
        exam_date=parsed_date,
        solution_pdf_path=pdf_path,
        processing_status="processing"
    )
    db.add(exam)
    db.commit()
    db.refresh(exam)
    
    # Process solution PDF
    try:
        print(f"[Exam {exam.id}] Step 1: Extracting text from PDF...", flush=True)
        solution_text = extract_solution_text(pdf_path)
        exam.solution_text = solution_text  # DEBUG: Save extracted text
        db.commit()
        
        print(f"[Exam {exam.id}] Step 2: Building question schema...", flush=True)
        schema = build_solution_schema(solution_text)
        exam.schema_json = schema  # DEBUG: Save schema
        db.commit()
        
        print(f"[Exam {exam.id}] Step 3: Extracting model answers...", flush=True)
        model_answers = build_model_answers(schema, solution_text)
        exam.model_answers_json = model_answers  # DEBUG: Save model answers
        
        exam.processing_status = "ready"
        db.commit()
        print(f"[Exam {exam.id}] Processing complete!", flush=True)
        
    except Exception as e:
        exam.processing_status = "failed"
        exam.processing_error = str(e)
        db.commit()
        print(f"[Exam {exam.id}] Processing failed: {e}", flush=True)
    
    return ExamResponse(
        id=exam.id,
        name=exam.name,
        subject=exam.subject,
        exam_date=exam.exam_date,
        processing_status=exam.processing_status,
        created_at=exam.created_at,
        student_count=0
    )


@router.get("/{exam_id}", response_model=ExamDetailResponse)
def get_exam(exam_id: int, db: Session = Depends(get_db)):
    """Get exam details including schema and model answers."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    return ExamDetailResponse(
        id=exam.id,
        name=exam.name,
        subject=exam.subject,
        exam_date=exam.exam_date,
        processing_status=exam.processing_status,
        created_at=exam.created_at,
        student_count=len(exam.student_papers),
        schema_json=exam.schema_json,
        model_answers_json=exam.model_answers_json,
        solution_text=exam.solution_text[:500] if exam.solution_text else None  # Truncated for response
    )


@router.get("/{exam_id}/students", response_model=List[StudentSummary])
def list_students(exam_id: int, db: Session = Depends(get_db)):
    """List all student papers for an exam."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    return [StudentSummary(
        id=s.id,
        student_name=s.student_name,
        roll_number=s.roll_number,
        status=s.status,
        obtained_marks=s.obtained_marks,
        total_marks=s.total_marks,
        percentage=s.percentage,
        grade=s.grade
    ) for s in exam.student_papers]


@router.delete("/{exam_id}")
def delete_exam(exam_id: int, db: Session = Depends(get_db)):
    """Delete an exam and all associated student papers."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    db.delete(exam)
    db.commit()
    
    return {"status": "deleted"}
