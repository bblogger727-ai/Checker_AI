from fastapi import APIRouter
from pydantic import BaseModel
import json
import os
from datetime import datetime

from app.services.model_answer_builder import build_model_answers

router = APIRouter()


class ModelAnswerRequest(BaseModel):
    questions_schema_path: str
    solution_text_path: str


@router.post("/build-model-answers")
def build_model_answers_api(data: ModelAnswerRequest):

    # Load question schema
    with open(data.questions_schema_path, "r", encoding="utf-8") as f:
        questions_schema = json.load(f)

    # Load solution text
    with open(data.solution_text_path, "r", encoding="utf-8") as f:
        solution_text = f.read()

    # Build model answers
    model_answer_schema = build_model_answers(questions_schema, solution_text)

    # Save output
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = f"question_schemas/model_answers_{timestamp}.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(model_answer_schema, f, indent=2, ensure_ascii=False)

    return {
        "status": "success",
        "model_answers_saved_to": output_path,
        "preview_questions": list(model_answer_schema.keys())
    }
