"""
Student Papers API Routes (PostgreSQL + Full Debug Storage)

Upload student papers and get grading results.
All intermediate steps saved for debugging.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import os

from app.core.database import get_db
from app.models import Exam, StudentPaper
from app.services.pdf_processor import pdf_to_images
from app.services.ocr_service import perform_ocr
from app.services.answer_aligner import align_answers_to_schema as align_answers
from app.services.answer_grader import grade_all_answers
from app.services.pdf_generator import generate_grading_pdf

router = APIRouter(prefix="/api/students", tags=["Student Papers"])


class StudentPaperResponse(BaseModel):
    id: int
    exam_id: int
    student_name: str
    roll_number: Optional[str] = None
    status: str
    obtained_marks: Optional[int] = None
    total_marks: Optional[int] = None
    percentage: Optional[int] = None
    grade: Optional[str] = None


class StudentDetailResponse(StudentPaperResponse):
    """Full response with debug data."""
    ocr_combined_text: Optional[str] = None
    aligned_answers_json: Optional[dict] = None
    grading_json: Optional[dict] = None


@router.post("/upload", response_model=StudentPaperResponse)
async def upload_student_paper(
    exam_id: int = Form(...),
    student_name: str = Form(...),
    roll_number: Optional[str] = Form(None),
    answer_pdf: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload a student answer paper for grading.
    Automatically runs OCR, alignment, and grading.
    All steps saved to database for debugging.
    """
    # Verify exam exists
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    if exam.processing_status != "ready":
        raise HTTPException(
            status_code=400, 
            detail="Exam is not ready. Wait for solution processing to complete."
        )
    
    # Create student directory
    student_dir = f"uploads/students/{exam_id}"
    os.makedirs(student_dir, exist_ok=True)
    
    # Save answer PDF
    pdf_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{student_name.replace(' ', '_')}.pdf"
    pdf_path = os.path.join(student_dir, pdf_filename)
    
    content = await answer_pdf.read()
    with open(pdf_path, "wb") as f:
        f.write(content)
    
    # Create student paper record
    student = StudentPaper(
        exam_id=exam_id,
        student_name=student_name,
        roll_number=roll_number,
        answer_pdf_path=pdf_path,
        status="processing"
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    
    # Process the paper
    try:
        # Step 1: PDF to Images
        print(f"[Student {student.id}] Step 1: Converting PDF to images...", flush=True)
        images = pdf_to_images(content)
        
        # Step 2: OCR each page
        print(f"[Student {student.id}] Step 2: Running OCR ({len(images)} pages)...", flush=True)
        ocr_pages = []
        for i, img in enumerate(images):
            print(f"[Student {student.id}] OCR page {i+1}/{len(images)}...", flush=True)
            text = perform_ocr(img)
            ocr_pages.append({"page": i + 1, "text": text})
        
        # DEBUG: Save OCR results
        student.ocr_pages_json = ocr_pages
        student.ocr_combined_text = "\n\n".join([f"=== Page {p['page']} ===\n{p['text']}" for p in ocr_pages])
        student.ocr_completed_at = datetime.utcnow()
        db.commit()
        
        # Step 3: Align answers to schema
        print(f"[Student {student.id}] Step 3: Aligning answers to schema...", flush=True)
        aligned = align_answers(ocr_pages, exam.schema_json)
        student.aligned_answers_json = aligned  # DEBUG: Save aligned
        student.aligned_at = datetime.utcnow()
        db.commit()
        
        # Step 4: Grade answers
        print(f"[Student {student.id}] Step 4: Grading answers...", flush=True)
        grading_result = grade_all_answers(aligned, exam.model_answers_json)
        student.grading_json = grading_result  # DEBUG: Save grading
        
        # Extract summary
        metadata = grading_result.get("metadata", {})
        student.total_marks = metadata.get("total_marks_possible", 0)
        student.obtained_marks = metadata.get("total_marks_obtained", 0)
        student.percentage = int(metadata.get("percentage", 0))
        student.grade = metadata.get("grade", "")
        student.graded_at = datetime.utcnow()
        student.status = "completed"
        db.commit()
        
        print(f"[Student {student.id}] Complete! {student.obtained_marks}/{student.total_marks} ({student.grade})", flush=True)
        
    except Exception as e:
        student.status = "failed"
        student.processing_error = str(e)
        db.commit()
        print(f"[Student {student.id}] Failed: {e}", flush=True)
    
    return StudentPaperResponse(
        id=student.id,
        exam_id=student.exam_id,
        student_name=student.student_name,
        roll_number=student.roll_number,
        status=student.status,
        obtained_marks=student.obtained_marks,
        total_marks=student.total_marks,
        percentage=student.percentage,
        grade=student.grade
    )


@router.get("/{student_id}", response_model=StudentDetailResponse)
def get_student_paper(student_id: int, db: Session = Depends(get_db)):
    """Get student paper details with debug data."""
    student = db.query(StudentPaper).filter(StudentPaper.id == student_id).first()
    
    if not student:
        raise HTTPException(status_code=404, detail="Student paper not found")
    
    return StudentDetailResponse(
        id=student.id,
        exam_id=student.exam_id,
        student_name=student.student_name,
        roll_number=student.roll_number,
        status=student.status,
        obtained_marks=student.obtained_marks,
        total_marks=student.total_marks,
        percentage=student.percentage,
        grade=student.grade,
        ocr_combined_text=student.ocr_combined_text[:1000] if student.ocr_combined_text else None,
        aligned_answers_json=student.aligned_answers_json,
        grading_json=student.grading_json
    )


@router.get("/{student_id}/result-pdf")
def download_result_pdf(student_id: int, db: Session = Depends(get_db)):
    """Download the graded result as PDF."""
    student = db.query(StudentPaper).filter(StudentPaper.id == student_id).first()
    
    if not student:
        raise HTTPException(status_code=404, detail="Student paper not found")
    
    if student.status != "completed":
        raise HTTPException(status_code=400, detail="Grading not completed")
    
    # Generate PDF if not exists
    if not student.graded_pdf_path or not os.path.exists(student.graded_pdf_path):
        exam = student.exam
        pdf_path = generate_grading_pdf(
            student_name=student.student_name,
            exam_name=exam.name,
            grading_json=student.grading_json,
            output_dir=f"uploads/results/{exam.id}"
        )
        student.graded_pdf_path = pdf_path
        db.commit()
    
    return FileResponse(
        student.graded_pdf_path,
        media_type="application/pdf",
        filename=f"{student.student_name}_result.pdf"
    )


@router.delete("/{student_id}")
def delete_student(student_id: int, db: Session = Depends(get_db)):
    """Delete a student paper."""
    student = db.query(StudentPaper).filter(StudentPaper.id == student_id).first()
    
    if not student:
        raise HTTPException(status_code=404, detail="Student paper not found")
    
    db.delete(student)
    db.commit()
    
    return {"status": "deleted"}
