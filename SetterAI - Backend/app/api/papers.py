"""
Papers API - Generate, edit, and publish exam papers.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from app.core.database import get_db
from app.models import GeneratedPaper, Subject, PaperTemplate, QuestionBank
from app.services.paper_generator import generate_paper_content
from app.services.solution_generator import generate_solution

router = APIRouter(prefix="/api/setter/papers", tags=["Generated Papers"])


class GenerateRequest(BaseModel):
    subject_id: int
    template_id: Optional[int] = None
    title: Optional[str] = None
    options: Optional[dict] = None  # Additional generation options


class PaperUpdate(BaseModel):
    edited_paper_json: dict


class PaperResponse(BaseModel):
    id: int
    subject_id: int
    template_id: Optional[int]
    title: str
    status: str
    generated_paper_json: Optional[dict]
    edited_paper_json: Optional[dict]
    final_paper_json: Optional[dict]
    solution_json: Optional[dict]
    linked_exam_id: Optional[int]
    created_at: datetime
    
    class Config:
        from_attributes = True


class PaperSummary(BaseModel):
    id: int
    title: str
    status: str
    subject_name: str
    created_at: datetime
    
    class Config:
        from_attributes = True


@router.get("", response_model=List[PaperSummary])
def list_papers(
    subject_id: Optional[int] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """List generated papers."""
    query = db.query(GeneratedPaper).join(Subject)
    
    if subject_id:
        query = query.filter(GeneratedPaper.subject_id == subject_id)
    if status:
        query = query.filter(GeneratedPaper.status == status)
    
    papers = query.order_by(GeneratedPaper.created_at.desc()).all()
    
    return [PaperSummary(
        id=p.id,
        title=p.title or f"Paper #{p.id}",
        status=p.status,
        subject_name=p.subject.name,
        created_at=p.created_at
    ) for p in papers]


@router.post("/generate", response_model=PaperResponse)
def generate_paper(data: GenerateRequest, db: Session = Depends(get_db)):
    """
    Generate a new exam paper using AI.
    
    Uses questions from the question bank, weighted by frequency score.
    """
    # Get subject
    subject = db.query(Subject).filter(Subject.id == data.subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")
    
    # Get template if provided
    template = None
    if data.template_id:
        template = db.query(PaperTemplate).filter(PaperTemplate.id == data.template_id).first()
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
    
    # Get questions for this subject
    questions = db.query(QuestionBank).filter(
        QuestionBank.subject_id == data.subject_id
    ).all()
    
    # Generate paper
    print(f"[SetterAI] Generating paper for {subject.name}...", flush=True)
    
    generated_content = generate_paper_content(
        subject=subject,
        template=template,
        questions=questions,
        options=data.options
    )
    
    # Create paper record
    title = data.title or f"{subject.name} - {template.name if template else 'Custom'} - {datetime.now().strftime('%b %Y')}"
    
    paper = GeneratedPaper(
        subject_id=subject.id,
        template_id=template.id if template else None,
        title=title,
        status="draft",
        generated_paper_json=generated_content,
        generation_config=data.options
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)
    
    print(f"[SetterAI] Paper generated: {paper.id}", flush=True)
    
    return paper


@router.get("/{paper_id}", response_model=PaperResponse)
def get_paper(paper_id: int, db: Session = Depends(get_db)):
    """Get paper details."""
    paper = db.query(GeneratedPaper).filter(GeneratedPaper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@router.put("/{paper_id}", response_model=PaperResponse)
def update_paper(paper_id: int, data: PaperUpdate, db: Session = Depends(get_db)):
    """Save edits to a paper."""
    paper = db.query(GeneratedPaper).filter(GeneratedPaper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    
    if paper.status in ["finalized", "published"]:
        raise HTTPException(status_code=400, detail="Cannot edit finalized/published paper")
    
    paper.edited_paper_json = data.edited_paper_json
    paper.edited_at = datetime.utcnow()
    paper.status = "reviewing"
    
    db.commit()
    db.refresh(paper)
    return paper


@router.post("/{paper_id}/finalize", response_model=PaperResponse)
def finalize_paper(paper_id: int, db: Session = Depends(get_db)):
    """Finalize a paper (lock for no more edits)."""
    paper = db.query(GeneratedPaper).filter(GeneratedPaper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    
    # Use edited version if available, otherwise use generated
    paper.final_paper_json = paper.edited_paper_json or paper.generated_paper_json
    paper.status = "finalized"
    paper.finalized_at = datetime.utcnow()
    
    db.commit()
    db.refresh(paper)
    return paper


@router.post("/{paper_id}/generate-solution", response_model=PaperResponse)
def generate_paper_solution(paper_id: int, db: Session = Depends(get_db)):
    """Generate solution for a finalized paper."""
    paper = db.query(GeneratedPaper).filter(GeneratedPaper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    
    if paper.status not in ["finalized", "published"]:
        raise HTTPException(status_code=400, detail="Paper must be finalized first")
    
    # Get subject for reference materials
    subject = paper.subject
    questions = db.query(QuestionBank).filter(
        QuestionBank.subject_id == subject.id
    ).all()
    
    print(f"[SetterAI] Generating solution for paper {paper_id}...", flush=True)
    
    # Generate solution using AI
    solution = generate_solution(
        paper_json=paper.final_paper_json,
        subject=subject,
        question_bank=questions
    )
    
    paper.solution_json = solution
    db.commit()
    db.refresh(paper)
    
    print(f"[SetterAI] Solution generated for paper {paper_id}", flush=True)
    
    return paper


@router.post("/{paper_id}/publish")
def publish_paper(paper_id: int, db: Session = Depends(get_db)):
    """
    Publish paper to CheckerAI exams.
    
    Creates an exam entry that can be used for grading student papers.
    """
    paper = db.query(GeneratedPaper).filter(GeneratedPaper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    
    if not paper.final_paper_json:
        raise HTTPException(status_code=400, detail="Paper must be finalized first")
    
    if not paper.solution_json:
        raise HTTPException(status_code=400, detail="Solution must be generated first")
    
    # TODO: Create entry in CheckerAI exams table
    # This will require cross-database integration or shared DB
    
    # For now, just mark as published
    paper.status = "published"
    paper.published_at = datetime.utcnow()
    # paper.linked_exam_id = created_exam.id
    
    db.commit()
    
    return {
        "status": "published",
        "paper_id": paper.id,
        "message": "Paper published successfully. Ready for student grading."
    }


@router.delete("/{paper_id}")
def delete_paper(paper_id: int, db: Session = Depends(get_db)):
    """Delete a paper (only drafts)."""
    paper = db.query(GeneratedPaper).filter(GeneratedPaper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    
    if paper.status == "published":
        raise HTTPException(status_code=400, detail="Cannot delete published paper")
    
    db.delete(paper)
    db.commit()
    return {"status": "deleted"}
