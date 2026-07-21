"""
Student Papers API Routes (PostgreSQL + Full Debug Storage)

Upload student papers and get grading results.
All intermediate steps saved for debugging.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime
import os
import json
import sys

from app.core.database import get_db
from app.models import Exam, StudentPaper
from app.services.pdf_processor import pdf_to_images
from app.services.ocr_service import perform_ocr
from app.services.answer_aligner import align_answers_to_schema as align_answers
from app.services.answer_grader import grade_all_answers
from app.services.pdf_generator import generate_grading_pdf
from app.services.checked_copy_annotator import checked_copy_path, generate_checked_copy_pdf

# Import patch utilities from generate_checked_copy_v2 / patch_checked_copy
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

try:
    from patch_checked_copy import get_manifest_summary, apply_patch
    _PATCH_AVAILABLE = True
except ImportError:
    _PATCH_AVAILABLE = False

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
    checked_copy_available: bool = False


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

        # Step 5: Generate annotated checked copy from the original answer PDF.
        try:
            print(f"[Student {student.id}] Step 5: Annotating checked copy...", flush=True)
            output_dir = f"uploads/checked/{exam.id}"
            output_path = checked_copy_path(student.id, student.student_name, output_dir)
            generate_checked_copy_pdf(
                answer_pdf_path=student.answer_pdf_path,
                grading_json=student.grading_json,
                output_path=output_path
            )
            print(f"[Student {student.id}] Checked copy ready: {output_path}", flush=True)
        except Exception as annotation_error:
            # Keep grading successful even if PDF annotation needs to be retried later.
            print(f"[Student {student.id}] Checked copy annotation failed: {annotation_error}", flush=True)
        
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
        grade=student.grade,
        checked_copy_available=_checked_copy_exists(student)
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
        checked_copy_available=_checked_copy_exists(student),
        ocr_combined_text=student.ocr_combined_text[:1000] if student.ocr_combined_text else None,
        aligned_answers_json=student.aligned_answers_json,
        grading_json=student.grading_json
    )


def _checked_copy_exists(student: StudentPaper) -> bool:
    path = checked_copy_path(student.id, student.student_name, f"uploads/checked/{student.exam_id}")
    return os.path.exists(path)


@router.get("/{student_id}/checked-copy-pdf")
def download_checked_copy_pdf(student_id: int, db: Session = Depends(get_db)):
    """Download the annotated checked copy of the student's original answer PDF."""
    student = db.query(StudentPaper).filter(StudentPaper.id == student_id).first()
    
    if not student:
        raise HTTPException(status_code=404, detail="Student paper not found")
    
    if student.status != "completed":
        raise HTTPException(status_code=400, detail="Grading not completed")
    
    if not student.answer_pdf_path or not os.path.exists(student.answer_pdf_path):
        raise HTTPException(status_code=404, detail="Original answer PDF not found")
    
    if not student.grading_json:
        raise HTTPException(status_code=400, detail="Grading data not available")
    
    output_dir = f"uploads/checked/{student.exam_id}"
    output_path = checked_copy_path(student.id, student.student_name, output_dir)
    
    if not os.path.exists(output_path):
        try:
            generate_checked_copy_pdf(
                answer_pdf_path=student.answer_pdf_path,
                grading_json=student.grading_json,
                output_path=output_path
            )
        except Exception as annotation_error:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to generate checked copy: {annotation_error}"
            )
    
    return FileResponse(
        output_path,
        media_type="application/pdf",
        filename=f"{student.student_name}_checked_copy.pdf"
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


# ══════════════════════════════════════════════════════════════════════════════
#  Annotation edit endpoints (powered by generate_checked_copy_v2 + patch_checked_copy)
# ══════════════════════════════════════════════════════════════════════════════

def _manifest_path(student: StudentPaper) -> str:
    """Derive the manifest JSON path from the checked-copy PDF path."""
    output_dir = f"uploads/checked/{student.exam_id}"
    cc_path = checked_copy_path(student.id, student.student_name, output_dir)
    stem, _ = os.path.splitext(cc_path)
    return stem + "_manifest.json"


@router.get("/{student_id}/manifest")
def get_annotation_manifest(student_id: int, db: Session = Depends(get_db)):
    """
    Return the annotation manifest for a completed, annotated student paper.

    The manifest lists every question with its current marks_obtained,
    marks_total, feedback text, and tick/cross list — ready to populate the
    frontend editor.
    """
    if not _PATCH_AVAILABLE:
        raise HTTPException(status_code=501, detail="Patch module not available on this server")

    student = db.query(StudentPaper).filter(StudentPaper.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student paper not found")
    if student.status != "completed":
        raise HTTPException(status_code=400, detail="Grading not yet completed")

    manifest_path = _manifest_path(student)
    if not os.path.exists(manifest_path):
        raise HTTPException(
            status_code=404,
            detail="Annotation manifest not found. Re-generate the checked copy with generate_checked_copy_v2.py first."
        )

    try:
        summary = get_manifest_summary(manifest_path)
        return JSONResponse(content=summary)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read manifest: {e}")


class TickCrossCorrection(BaseModel):
    index: int
    action: str   # "tick" or "cross"


class QuestionCorrection(BaseModel):
    marks_obtained: Optional[float] = None
    marks_total:    Optional[float] = None
    feedback_text:  Optional[str]   = None
    ticks_crosses:  Optional[list]  = None   # list of TickCrossCorrection dicts


class PatchRequest(BaseModel):
    corrections: dict   # manifest_key → QuestionCorrection dict


@router.post("/{student_id}/patch")
def patch_checked_copy_pdf(
    student_id: int,
    body: PatchRequest,
    db: Session = Depends(get_db),
):
    """
    Apply mark / feedback / tick-cross corrections to a student's checked copy.

    The original annotated PDF is NOT modified.  A new patched PDF is generated
    and returned as a file download. The updated manifest is saved alongside it.

    Request body:
    {
      "corrections": {
        "SectionB__Q1": {
          "marks_obtained": 5.0,
          "feedback_text": "Include interest workings"
        }
      }
    }
    """
    if not _PATCH_AVAILABLE:
        raise HTTPException(status_code=501, detail="Patch module not available on this server")

    student = db.query(StudentPaper).filter(StudentPaper.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student paper not found")
    if student.status != "completed":
        raise HTTPException(status_code=400, detail="Grading not yet completed")

    manifest_path = _manifest_path(student)
    if not os.path.exists(manifest_path):
        raise HTTPException(
            status_code=404,
            detail="Annotation manifest not found. Generate the checked copy with generate_checked_copy_v2.py first."
        )

    # Build output path: always a fixed "patched" name beside the original
    output_dir = f"uploads/checked/{student.exam_id}"
    os.makedirs(output_dir, exist_ok=True)

    safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_"
                        for ch in student.student_name).strip("_") or "student"
    patched_pdf_path = os.path.join(
        output_dir, f"{safe_name}_{student_id}_checked_copy_patched.pdf"
    )

    try:
        apply_patch(
            manifest_path=manifest_path,
            corrections=body.corrections,
            output_path=patched_pdf_path,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Patch failed: {e}")

    return FileResponse(
        patched_pdf_path,
        media_type="application/pdf",
        filename=f"{student.student_name}_checked_copy_edited.pdf",
    )

