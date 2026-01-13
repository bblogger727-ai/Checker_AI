from fastapi import APIRouter, UploadFile, File
import os
from datetime import datetime
import json
import tempfile

from app.services.solution_text_extractor import extract_solution_text

from app.services.solution_schema_builder import build_solution_schema

router = APIRouter()


@router.post("/upload-solution-pdf")
async def upload_solution_pdf(file: UploadFile = File(...)):
    print(f"[Solution Upload] Received file: {file.filename}", flush=True)

    # Save temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        content = await file.read()
        tmp.write(content)
        temp_path = tmp.name

    print("[Solution Upload] Temporary file saved", flush=True)

    # Extract text
    print("[Solution Upload] Extracting text from PDF...", flush=True)
    solution_text = extract_solution_text(temp_path)
    print(f"[Solution Upload] Text extracted ({len(solution_text)} characters)", flush=True)

    # Build schema
    print("[Solution Upload] Building question schema using OpenAI...", flush=True)
    schema = build_solution_schema(solution_text)
    print("[Solution Upload] Schema generated successfully", flush=True)

    # Save schema
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    schema_path = f"question_schemas/schema_{timestamp}.json"

    with open(schema_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)

    print(f"[Solution Upload] Schema saved to {schema_path}", flush=True)

    # Cleanup
    os.remove(temp_path)

    print("[Solution Upload] Done.", flush=True)

    return {
        "status": "success",
        "schema_saved_to": schema_path,
        "schema_preview": schema
    }
