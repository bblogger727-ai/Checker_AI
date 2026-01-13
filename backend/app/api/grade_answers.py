"""
Grade Answers API Endpoint

Grades student answers against model answers using hybrid approach:
- MCQs: Fast fuzzy string matching
- Descriptive: GPT-based evaluation
"""

from fastapi import APIRouter
from pydantic import BaseModel
import json
import os
from datetime import datetime

from app.services.answer_grader import grade_all_answers

router = APIRouter()


class GradeRequest(BaseModel):
    aligned_answers_path: str
    model_answers_path: str


@router.post("/grade-student-answers")
def grade_student_answers(data: GradeRequest):
    print(f"[Grading] Starting grading process...", flush=True)
    print(f"[Grading] Aligned answers: {data.aligned_answers_path}", flush=True)
    print(f"[Grading] Model answers: {data.model_answers_path}", flush=True)
    
    # Load aligned student answers
    with open(data.aligned_answers_path, "r", encoding="utf-8") as f:
        aligned_answers = json.load(f)
    print(f"[Grading] Loaded aligned answers", flush=True)
    
    # Load model answers
    with open(data.model_answers_path, "r", encoding="utf-8") as f:
        model_answers = json.load(f)
    print(f"[Grading] Loaded model answers", flush=True)
    
    # Grade all answers
    print(f"[Grading] Grading answers (MCQs via fuzzy match, descriptive via GPT)...", flush=True)
    grading_results = grade_all_answers(aligned_answers, model_answers)
    print(f"[Grading] Grading complete!", flush=True)
    
    # Save results
    os.makedirs("grading_results", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = f"grading_results/grading_{timestamp}.json"
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(grading_results, f, indent=2, ensure_ascii=False)
    
    print(f"[Grading] Results saved to {output_path}", flush=True)
    
    metadata = grading_results.get("metadata", {})
    
    return {
        "status": "success",
        "grading_saved_to": output_path,
        "summary": {
            "total_questions": metadata.get("total_questions", 0),
            "mcq_questions": metadata.get("mcq_questions", 0),
            "descriptive_questions": metadata.get("descriptive_questions", 0),
            "total_marks_obtained": metadata.get("total_marks_obtained", 0),
            "total_marks_possible": metadata.get("total_marks_possible", 0),
            "percentage": metadata.get("percentage", 0),
            "grade": metadata.get("grade", "N/A")
        }
    }
