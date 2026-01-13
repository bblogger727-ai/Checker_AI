"""
Problems API - List and create problems.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.models import ProblemCategory, Problem

router = APIRouter(prefix="/api/mentor/problems", tags=["Problems"])


class ProblemCreate(BaseModel):
    category_id: int
    title: str
    description: Optional[str] = None
    default_solution: Optional[str] = None


@router.get("")
def list_problems(db: Session = Depends(get_db)):
    """Get all problems grouped by category."""
    categories = db.query(ProblemCategory).order_by(ProblemCategory.order_index).all()
    
    result = []
    for category in categories:
        problems = db.query(Problem).filter(
            Problem.category_id == category.id
        ).order_by(Problem.title).all()
        
        result.append({
            "id": category.id,
            "name": category.name,
            "icon": category.icon,
            "problems": [
                {
                    "id": p.id,
                    "title": p.title,
                    "description": p.description,
                    "default_solution": p.default_solution,
                    "is_custom": p.is_custom
                }
                for p in problems
            ]
        })
    
    return result


@router.post("")
def create_problem(data: ProblemCreate, db: Session = Depends(get_db)):
    """Add a custom problem."""
    category = db.query(ProblemCategory).filter(ProblemCategory.id == data.category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    
    problem = Problem(
        category_id=data.category_id,
        title=data.title,
        description=data.description,
        default_solution=data.default_solution,
        is_custom=True
    )
    db.add(problem)
    db.commit()
    db.refresh(problem)
    
    return {
        "id": problem.id,
        "title": problem.title,
        "category": category.name,
        "message": "Problem added"
    }


@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    """Get just the category list."""
    categories = db.query(ProblemCategory).order_by(ProblemCategory.order_index).all()
    return [
        {"id": c.id, "name": c.name, "icon": c.icon}
        for c in categories
    ]
