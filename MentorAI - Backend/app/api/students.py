"""
Students API - CRUD and profile management.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime

from app.core.database import get_db
from app.models import Student, StudentExam, Consultation

router = APIRouter(prefix="/api/mentor/students", tags=["Students"])


# Pydantic schemas
class StudentCreate(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None


class StudentUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None


class StudentResponse(BaseModel):
    id: int
    student_id: str
    name: str
    phone: Optional[str]
    email: Optional[str]
    notes: Optional[str]
    enrollment_date: datetime
    exam_count: int = 0
    consultation_count: int = 0
    last_exam_date: Optional[datetime] = None
    last_consultation_date: Optional[datetime] = None
    average_percentage: Optional[float] = None


def generate_student_id(db: Session) -> str:
    """Generate next student ID like STU001, STU002, etc."""
    last_student = db.query(Student).order_by(Student.id.desc()).first()
    next_num = (last_student.id + 1) if last_student else 1
    return f"STU{next_num:03d}"


@router.get("")
def list_students(
    search: Optional[str] = Query(None, description="Search by name or ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """List all students with stats."""
    query = db.query(Student)
    
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Student.name.ilike(search_term),
                Student.student_id.ilike(search_term)
            )
        )
    
    total = query.count()
    students = query.order_by(Student.name).offset(offset).limit(limit).all()
    
    result = []
    for student in students:
        # Get stats
        exam_count = db.query(StudentExam).filter(StudentExam.student_id == student.id).count()
        consultation_count = db.query(Consultation).filter(Consultation.student_id == student.id).count()
        
        last_exam = db.query(StudentExam).filter(
            StudentExam.student_id == student.id
        ).order_by(StudentExam.exam_date.desc()).first()
        
        last_consultation = db.query(Consultation).filter(
            Consultation.student_id == student.id
        ).order_by(Consultation.consultation_date.desc()).first()
        
        avg_percentage = db.query(func.avg(StudentExam.percentage)).filter(
            StudentExam.student_id == student.id
        ).scalar()
        
        result.append({
            "id": student.id,
            "student_id": student.student_id,
            "name": student.name,
            "phone": student.phone,
            "email": student.email,
            "enrollment_date": student.enrollment_date,
            "exam_count": exam_count,
            "consultation_count": consultation_count,
            "last_exam_date": last_exam.exam_date if last_exam else None,
            "last_consultation_date": last_consultation.consultation_date if last_consultation else None,
            "average_percentage": round(avg_percentage, 1) if avg_percentage else None
        })
    
    return {"total": total, "students": result}


@router.post("")
def create_student(data: StudentCreate, db: Session = Depends(get_db)):
    """Create a new student."""
    student = Student(
        student_id=generate_student_id(db),
        name=data.name,
        phone=data.phone,
        email=data.email,
        notes=data.notes
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    
    return {
        "id": student.id,
        "student_id": student.student_id,
        "name": student.name,
        "message": f"Student created. Recommend using '{student.student_id}' as PDF filename."
    }


@router.get("/{student_id}")
def get_student(student_id: int, db: Session = Depends(get_db)):
    """Get full student profile with exams and consultations."""
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    # Get exams
    exams = db.query(StudentExam).filter(
        StudentExam.student_id == student.id
    ).order_by(StudentExam.exam_date.desc()).all()
    
    # Get consultations
    consultations = db.query(Consultation).filter(
        Consultation.student_id == student.id
    ).order_by(Consultation.consultation_date.desc()).all()
    
    # Calculate stats
    avg_percentage = db.query(func.avg(StudentExam.percentage)).filter(
        StudentExam.student_id == student.id
    ).scalar()
    
    # Performance trend (last 5 exams)
    recent_exams = exams[:5] if len(exams) >= 5 else exams
    if len(recent_exams) >= 2:
        first_score = recent_exams[-1].percentage or 0
        last_score = recent_exams[0].percentage or 0
        trend = "improving" if last_score > first_score else "declining" if last_score < first_score else "stable"
    else:
        trend = "insufficient_data"
    
    return {
        "id": student.id,
        "student_id": student.student_id,
        "name": student.name,
        "phone": student.phone,
        "email": student.email,
        "notes": student.notes,
        "enrollment_date": student.enrollment_date,
        "stats": {
            "total_exams": len(exams),
            "total_consultations": len(consultations),
            "average_percentage": round(avg_percentage, 1) if avg_percentage else None,
            "trend": trend
        },
        "exams": [
            {
                "id": e.id,
                "exam_name": e.exam_name,
                "subject": e.subject,
                "exam_date": e.exam_date,
                "obtained_marks": e.obtained_marks,
                "total_marks": e.total_marks,
                "percentage": e.percentage,
                "grade": e.grade
            }
            for e in exams
        ],
        "consultations": [
            {
                "id": c.id,
                "date": c.consultation_date,
                "problems": c.problems_json,
                "custom_problem": c.custom_problem_text,
                "solution_preview": (c.generated_solution[:200] + "...") if c.generated_solution and len(c.generated_solution) > 200 else c.generated_solution,
                "sent_via": c.sent_via,
                "delivery_status": c.delivery_status
            }
            for c in consultations
        ]
    }


@router.put("/{student_id}")
def update_student(student_id: int, data: StudentUpdate, db: Session = Depends(get_db)):
    """Update student details."""
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    if data.name:
        student.name = data.name
    if data.phone is not None:
        student.phone = data.phone
    if data.email is not None:
        student.email = data.email
    if data.notes is not None:
        student.notes = data.notes
    
    db.commit()
    
    return {"message": "Updated", "student_id": student.student_id}


@router.delete("/{student_id}")
def delete_student(student_id: int, db: Session = Depends(get_db)):
    """Delete a student and all related data."""
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    db.delete(student)
    db.commit()
    
    return {"message": "Deleted"}


@router.get("/{student_id}/exams")
def get_student_exams(student_id: int, db: Session = Depends(get_db)):
    """Get all exams for a student."""
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    exams = db.query(StudentExam).filter(
        StudentExam.student_id == student.id
    ).order_by(StudentExam.exam_date.desc()).all()
    
    return [
        {
            "id": e.id,
            "exam_name": e.exam_name,
            "subject": e.subject,
            "exam_date": e.exam_date,
            "obtained_marks": e.obtained_marks,
            "total_marks": e.total_marks,
            "percentage": e.percentage,
            "grade": e.grade,
            "grading_details": e.grading_json
        }
        for e in exams
    ]


@router.get("/{student_id}/consultations")
def get_student_consultations(student_id: int, db: Session = Depends(get_db)):
    """Get all consultations for a student."""
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    consultations = db.query(Consultation).filter(
        Consultation.student_id == student.id
    ).order_by(Consultation.consultation_date.desc()).all()
    
    return [
        {
            "id": c.id,
            "date": c.consultation_date,
            "problems": c.problems_json,
            "custom_problem": c.custom_problem_text,
            "mentor_notes": c.mentor_notes,
            "generated_solution": c.generated_solution,
            "report_pdf_path": c.report_pdf_path,
            "sent_via": c.sent_via,
            "delivery_status": c.delivery_status
        }
        for c in consultations
    ]
