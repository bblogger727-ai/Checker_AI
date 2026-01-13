"""
Paper Templates API - Manage paper format templates.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List

from app.core.database import get_db
from app.models import PaperTemplate, Subject

router = APIRouter(prefix="/api/setter/templates", tags=["Paper Templates"])


class TemplateCreate(BaseModel):
    subject_id: int
    name: str
    paper_type: str  # "Full", "Portionwise", "Mock", "Topic-wise"
    total_marks: int
    duration_minutes: int
    format_json: dict
    topics_included: Optional[List[str]] = None


class TemplateResponse(BaseModel):
    id: int
    subject_id: int
    name: str
    paper_type: str
    total_marks: int
    duration_minutes: int
    format_json: dict
    topics_included: Optional[List[str]]
    
    class Config:
        from_attributes = True


@router.get("", response_model=List[TemplateResponse])
def list_templates(
    subject_id: Optional[int] = Query(None),
    paper_type: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """List paper templates."""
    query = db.query(PaperTemplate)
    
    if subject_id:
        query = query.filter(PaperTemplate.subject_id == subject_id)
    if paper_type:
        query = query.filter(PaperTemplate.paper_type == paper_type)
    
    return query.order_by(PaperTemplate.name).all()


@router.post("", response_model=TemplateResponse)
def create_template(data: TemplateCreate, db: Session = Depends(get_db)):
    """Create a paper template."""
    # Verify subject exists
    subject = db.query(Subject).filter(Subject.id == data.subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")
    
    template = PaperTemplate(
        subject_id=data.subject_id,
        name=data.name,
        paper_type=data.paper_type,
        total_marks=data.total_marks,
        duration_minutes=data.duration_minutes,
        format_json=data.format_json,
        topics_included=data.topics_included
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    
    return template


@router.get("/{template_id}", response_model=TemplateResponse)
def get_template(template_id: int, db: Session = Depends(get_db)):
    """Get template details."""
    template = db.query(PaperTemplate).filter(PaperTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.put("/{template_id}", response_model=TemplateResponse)
def update_template(template_id: int, data: TemplateCreate, db: Session = Depends(get_db)):
    """Update a template."""
    template = db.query(PaperTemplate).filter(PaperTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    template.name = data.name
    template.paper_type = data.paper_type
    template.total_marks = data.total_marks
    template.duration_minutes = data.duration_minutes
    template.format_json = data.format_json
    template.topics_included = data.topics_included
    
    db.commit()
    db.refresh(template)
    return template


@router.delete("/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db)):
    """Delete a template."""
    template = db.query(PaperTemplate).filter(PaperTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    db.delete(template)
    db.commit()
    return {"status": "deleted"}
