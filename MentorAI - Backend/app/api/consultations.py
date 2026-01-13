"""
Consultations API - Create sessions and generate reports.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime

from app.core.database import get_db
from app.models import Student, StudentExam, Consultation, Problem
from app.services.report_generator import generate_report
from app.services.email_sender import send_email_report
from app.services.whatsapp_sender import generate_whatsapp_link

router = APIRouter(prefix="/api/mentor/consultations", tags=["Consultations"])


class ProblemSelection(BaseModel):
    problem_id: int
    notes: Optional[str] = None


class ConsultationCreate(BaseModel):
    student_id: int
    problems: List[ProblemSelection]
    custom_problem_text: Optional[str] = None
    mentor_notes: Optional[str] = None


class SendReportRequest(BaseModel):
    send_whatsapp: bool = False
    send_email: bool = False


@router.post("")
def create_consultation(data: ConsultationCreate, db: Session = Depends(get_db)):
    """Create a new consultation session."""
    student = db.query(Student).filter(Student.id == data.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    # Validate problems exist
    problem_ids = [p.problem_id for p in data.problems]
    problems = db.query(Problem).filter(Problem.id.in_(problem_ids)).all()
    if len(problems) != len(problem_ids):
        raise HTTPException(status_code=400, detail="One or more problems not found")
    
    # Create consultation
    consultation = Consultation(
        student_id=student.id,
        problems_json=[{"problem_id": p.problem_id, "notes": p.notes} for p in data.problems],
        custom_problem_text=data.custom_problem_text,
        mentor_notes=data.mentor_notes
    )
    db.add(consultation)
    db.commit()
    db.refresh(consultation)
    
    return {
        "id": consultation.id,
        "student": student.name,
        "problems_count": len(data.problems),
        "message": "Consultation created. Call /generate-report to create PDF."
    }


@router.get("/{consultation_id}")
def get_consultation(consultation_id: int, db: Session = Depends(get_db)):
    """Get consultation details."""
    consultation = db.query(Consultation).filter(Consultation.id == consultation_id).first()
    if not consultation:
        raise HTTPException(status_code=404, detail="Consultation not found")
    
    student = consultation.student
    
    # Get problem titles
    problem_titles = []
    if consultation.problems_json:
        for p in consultation.problems_json:
            problem = db.query(Problem).filter(Problem.id == p.get("problem_id")).first()
            if problem:
                problem_titles.append({
                    "title": problem.title,
                    "category": problem.category.name if problem.category else None,
                    "notes": p.get("notes")
                })
    
    return {
        "id": consultation.id,
        "student": {
            "id": student.id,
            "student_id": student.student_id,
            "name": student.name,
            "phone": student.phone,
            "email": student.email
        },
        "consultation_date": consultation.consultation_date,
        "problems": problem_titles,
        "custom_problem": consultation.custom_problem_text,
        "mentor_notes": consultation.mentor_notes,
        "generated_solution": consultation.generated_solution,
        "report_pdf_path": consultation.report_pdf_path,
        "sent_via": consultation.sent_via,
        "sent_at": consultation.sent_at,
        "delivery_status": consultation.delivery_status
    }


@router.post("/{consultation_id}/generate-report")
def generate_consultation_report(consultation_id: int, db: Session = Depends(get_db)):
    """Generate personalized PDF report using LLM."""
    consultation = db.query(Consultation).filter(Consultation.id == consultation_id).first()
    if not consultation:
        raise HTTPException(status_code=404, detail="Consultation not found")
    
    student = consultation.student
    
    # Get student's exam history
    exams = db.query(StudentExam).filter(
        StudentExam.student_id == student.id
    ).order_by(StudentExam.exam_date.desc()).limit(10).all()
    
    # Get past consultations
    past_consultations = db.query(Consultation).filter(
        Consultation.student_id == student.id,
        Consultation.id != consultation.id
    ).order_by(Consultation.consultation_date.desc()).limit(5).all()
    
    # Get current problems
    current_problems = []
    if consultation.problems_json:
        for p in consultation.problems_json:
            problem = db.query(Problem).filter(Problem.id == p.get("problem_id")).first()
            if problem:
                current_problems.append({
                    "title": problem.title,
                    "category": problem.category.name if problem.category else "Other",
                    "default_solution": problem.default_solution,
                    "notes": p.get("notes")
                })
    
    # Generate report
    try:
        result = generate_report(
            student=student,
            exams=exams,
            current_problems=current_problems,
            custom_problem=consultation.custom_problem_text,
            past_consultations=past_consultations,
            mentor_notes=consultation.mentor_notes,
            db=db
        )
        
        # Update consultation
        consultation.llm_prompt = result.get("prompt")
        consultation.llm_response = result.get("llm_response")
        consultation.generated_solution = result.get("solution")
        consultation.report_pdf_path = result.get("pdf_path")
        db.commit()
        
        return {
            "message": "Report generated",
            "pdf_path": result.get("pdf_path"),
            "solution_preview": result.get("solution")[:500] if result.get("solution") else None
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {str(e)}")


@router.post("/{consultation_id}/send")
def send_consultation_report(
    consultation_id: int,
    data: SendReportRequest,
    db: Session = Depends(get_db)
):
    """Send report via WhatsApp and/or Email."""
    consultation = db.query(Consultation).filter(Consultation.id == consultation_id).first()
    if not consultation:
        raise HTTPException(status_code=404, detail="Consultation not found")
    
    if not consultation.report_pdf_path:
        raise HTTPException(status_code=400, detail="Report not generated yet. Call /generate-report first.")
    
    student = consultation.student
    results = {"whatsapp": None, "email": None}
    sent_methods = []
    
    # Send WhatsApp
    if data.send_whatsapp:
        if not student.phone:
            results["whatsapp"] = {"error": "No phone number on file"}
        else:
            try:
                wa_link = generate_whatsapp_link(
                    phone=student.phone,
                    student_name=student.name,
                    pdf_path=consultation.report_pdf_path
                )
                results["whatsapp"] = {"link": wa_link, "status": "link_generated"}
                sent_methods.append("whatsapp")
            except Exception as e:
                results["whatsapp"] = {"error": str(e)}
    
    # Send Email
    if data.send_email:
        if not student.email:
            results["email"] = {"error": "No email on file"}
        else:
            try:
                email_result = send_email_report(
                    to_email=student.email,
                    student_name=student.name,
                    pdf_path=consultation.report_pdf_path,
                    solution_text=consultation.generated_solution
                )
                results["email"] = {"status": "sent" if email_result else "failed"}
                if email_result:
                    sent_methods.append("email")
            except Exception as e:
                results["email"] = {"error": str(e)}
    
    # Update consultation
    if sent_methods:
        consultation.sent_via = ",".join(sent_methods)
        consultation.sent_at = datetime.utcnow()
        consultation.delivery_status = "sent"
        db.commit()
    
    return {
        "message": "Send operation completed",
        "results": results,
        "sent_via": consultation.sent_via
    }
