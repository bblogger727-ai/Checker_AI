"""
Link API - Auto-link papers from CheckerAI to student profiles.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
from pydantic import BaseModel
from datetime import datetime
from difflib import SequenceMatcher

from app.core.database import get_db
from app.models import Student, StudentExam

router = APIRouter(prefix="/api/mentor", tags=["Integration"])


class LinkPaperRequest(BaseModel):
    student_name: str
    roll_number: Optional[str] = None
    checker_paper_id: int
    exam_name: str
    subject: Optional[str] = None
    exam_date: Optional[datetime] = None
    total_marks: float
    obtained_marks: float
    percentage: float
    grade: Optional[str] = None
    grading_json: Optional[dict] = None


def fuzzy_match_name(name1: str, name2: str) -> float:
    """Calculate similarity between two names."""
    # Normalize names
    n1 = name1.lower().strip()
    n2 = name2.lower().strip()
    
    # Exact match
    if n1 == n2:
        return 1.0
    
    # Use SequenceMatcher for fuzzy matching
    return SequenceMatcher(None, n1, n2).ratio()


def find_student_by_name(db: Session, name: str, roll_number: Optional[str] = None) -> Optional[Student]:
    """
    Find student by name (fuzzy match) or roll number.
    Returns best match if similarity > 0.8
    """
    # First try exact match on student_id (if roll_number provided as STU###)
    if roll_number:
        student = db.query(Student).filter(
            func.lower(Student.student_id) == roll_number.lower()
        ).first()
        if student:
            return student
    
    # Try exact name match
    student = db.query(Student).filter(
        func.lower(Student.name) == name.lower()
    ).first()
    if student:
        return student
    
    # Fuzzy match on name
    all_students = db.query(Student).all()
    best_match = None
    best_score = 0.0
    
    for s in all_students:
        score = fuzzy_match_name(name, s.name)
        if score > best_score and score > 0.8:  # 80% similarity threshold
            best_score = score
            best_match = s
    
    return best_match


def generate_student_id(db: Session) -> str:
    """Generate next student ID like STU001, STU002, etc."""
    last_student = db.query(Student).order_by(Student.id.desc()).first()
    next_num = (last_student.id + 1) if last_student else 1
    return f"STU{next_num:03d}"


@router.post("/link-paper")
def link_paper_to_student(data: LinkPaperRequest, db: Session = Depends(get_db)):
    """
    Auto-link a graded paper from CheckerAI to a student profile.
    Creates new student if not found.
    """
    
    # Try to find existing student
    student = find_student_by_name(db, data.student_name, data.roll_number)
    created_new = False
    
    if not student:
        # Create new student
        student = Student(
            student_id=generate_student_id(db),
            name=data.student_name
        )
        db.add(student)
        db.flush()  # Get ID
        created_new = True
        print(f"[MentorAI] Created new student: {student.student_id} - {student.name}", flush=True)
    
    # Check if this paper is already linked
    existing = db.query(StudentExam).filter(
        StudentExam.checker_paper_id == data.checker_paper_id
    ).first()
    
    if existing:
        return {
            "message": "Paper already linked",
            "student_id": student.student_id,
            "student_name": student.name,
            "exam_id": existing.id
        }
    
    # Create exam record
    exam = StudentExam(
        student_id=student.id,
        checker_paper_id=data.checker_paper_id,
        exam_name=data.exam_name,
        subject=data.subject,
        exam_date=data.exam_date or datetime.utcnow(),
        total_marks=data.total_marks,
        obtained_marks=data.obtained_marks,
        percentage=data.percentage,
        grade=data.grade,
        grading_json=data.grading_json
    )
    db.add(exam)
    db.commit()
    
    return {
        "message": "Paper linked successfully",
        "student_id": student.student_id,
        "student_name": student.name,
        "created_new_student": created_new,
        "exam_id": exam.id,
        "recommendation": f"Student should use '{student.student_id}' as PDF filename for future submissions."
    }
