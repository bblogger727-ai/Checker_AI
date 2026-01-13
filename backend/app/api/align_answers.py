from fastapi import APIRouter
from pydantic import BaseModel
import json
import os
from datetime import datetime

from app.services.answer_aligner import align_answers_to_schema

router = APIRouter()


class AlignRequest(BaseModel):
    ocr_folder_path: str
    schema_path: str


@router.post("/align-student-answers")
def align_student_answers(data: AlignRequest):
    # Load student OCR
    raw_pages_path = os.path.join(data.ocr_folder_path, "raw_pages.json")
    with open(raw_pages_path, "r", encoding="utf-8") as f:
        student_pages = json.load(f)

    # Load solution schema
    with open(data.schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)

    # Align
    aligned = align_answers_to_schema(student_pages, schema)

    # Save aligned output
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = f"aligned_outputs/aligned_{timestamp}.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(aligned, f, indent=2, ensure_ascii=False)

    return {
        "status": "success",
        "aligned_saved_to": output_path,
        "aligned_answers": aligned
    }
