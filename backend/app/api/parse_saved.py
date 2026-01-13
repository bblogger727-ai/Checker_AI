from fastapi import APIRouter
from pydantic import BaseModel
import json
import os

from app.services.answer_parser import parse_answers

router = APIRouter()


class ParseRequest(BaseModel):
    folder_path: str


@router.post("/parse-from-ocr-folder")
def parse_from_saved_ocr(data: ParseRequest):
    folder_path = data.folder_path

    raw_json_path = os.path.join(folder_path, "raw_pages.json")

    if not os.path.exists(raw_json_path):
        return {
            "status": "error",
            "message": f"raw_pages.json not found in {folder_path}"
        }

    with open(raw_json_path, "r", encoding="utf-8") as f:
        raw_pages = json.load(f)

    structured_answers = parse_answers(raw_pages)

    return {
        "status": "success",
        "structured_answers": structured_answers
    }
