"""
Dashboard API - Stats and quick views.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta

from app.core.database import get_db
from app.models import Student, StudentExam, Consultation

router = APIRouter(prefix="/api/mentor/dashboard", tags=["Dashboard"])


@router.get("/stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    """Get overall dashboard statistics."""
    
    # Total counts
    total_students = db.query(Student).count()
    total_exams = db.query(StudentExam).count()
    total_consultations = db.query(Consultation).count()
    
    # This week's stats
    week_ago = datetime.utcnow() - timedelta(days=7)
    
    consultations_this_week = db.query(Consultation).filter(
        Consultation.consultation_date >= week_ago
    ).count()
    
    exams_this_week = db.query(StudentExam).filter(
        StudentExam.created_at >= week_ago
    ).count()
    
    new_students_this_week = db.query(Student).filter(
        Student.created_at >= week_ago
    ).count()
    
    # Average performance
    avg_percentage = db.query(func.avg(StudentExam.percentage)).scalar()
    
    # Pending follow-ups (students with no consultation in 7+ days)
    students_with_recent_consult = db.query(Consultation.student_id).filter(
        Consultation.consultation_date >= week_ago
    ).distinct().subquery()
    
    pending_followup = db.query(Student).filter(
        ~Student.id.in_(students_with_recent_consult)
    ).count()
    
    return {
        "total_students": total_students,
        "total_exams": total_exams,
        "total_consultations": total_consultations,
        "consultations_this_week": consultations_this_week,
        "exams_this_week": exams_this_week,
        "new_students_this_week": new_students_this_week,
        "average_performance": round(avg_percentage, 1) if avg_percentage else None,
        "pending_followup_count": pending_followup
    }


@router.get("/recent")
def get_recent_activity(
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """Get recent consultations."""
    consultations = db.query(Consultation).order_by(
        Consultation.consultation_date.desc()
    ).limit(limit).all()
    
    return [
        {
            "id": c.id,
            "student_name": c.student.name,
            "student_id": c.student.student_id,
            "date": c.consultation_date,
            "problems_count": len(c.problems_json) if c.problems_json else 0,
            "has_report": c.report_pdf_path is not None,
            "delivery_status": c.delivery_status
        }
        for c in consultations
    ]


@router.get("/pending-followup")
def get_pending_followups(db: Session = Depends(get_db)):
    """Get students who need follow-up (no consultation in 7+ days)."""
    week_ago = datetime.utcnow() - timedelta(days=7)
    
    # Students with at least one consultation, but not in last 7 days
    students_with_consultation = db.query(Student).join(Consultation).all()
    
    result = []
    for student in students_with_consultation:
        last_consult = db.query(Consultation).filter(
            Consultation.student_id == student.id
        ).order_by(Consultation.consultation_date.desc()).first()
        
        if last_consult and last_consult.consultation_date < week_ago:
            days_since = (datetime.utcnow() - last_consult.consultation_date).days
            result.append({
                "student_id": student.id,
                "student_code": student.student_id,
                "name": student.name,
                "last_consultation": last_consult.consultation_date,
                "days_since": days_since
            })
    
    # Also include students with exams but no consultations
    students_with_exams_only = db.query(Student).join(StudentExam).outerjoin(Consultation).filter(
        Consultation.id == None
    ).all()
    
    for student in students_with_exams_only:
        result.append({
            "student_id": student.id,
            "student_code": student.student_id,
            "name": student.name,
            "last_consultation": None,
            "days_since": None,
            "note": "Has exams but no consultations yet"
        })
    
    # Sort by days since last consultation (most urgent first)
    result.sort(key=lambda x: x.get("days_since") or 999, reverse=True)
    
    return result


@router.get("/top-performers")
def get_top_performers(limit: int = 5, db: Session = Depends(get_db)):
    """Get top performing students by average percentage."""
    from sqlalchemy import desc
    
    subquery = db.query(
        StudentExam.student_id,
        func.avg(StudentExam.percentage).label("avg_pct"),
        func.count(StudentExam.id).label("exam_count")
    ).group_by(StudentExam.student_id).having(
        func.count(StudentExam.id) >= 2  # At least 2 exams
    ).subquery()
    
    results = db.query(
        Student,
        subquery.c.avg_pct,
        subquery.c.exam_count
    ).join(subquery, Student.id == subquery.c.student_id).order_by(
        desc(subquery.c.avg_pct)
    ).limit(limit).all()
    
    return [
        {
            "student_id": student.id,
            "student_code": student.student_id,
            "name": student.name,
            "average_percentage": round(avg_pct, 1),
            "exam_count": exam_count
        }
        for student, avg_pct, exam_count in results
    ]
