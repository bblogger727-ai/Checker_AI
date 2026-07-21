from fastapi import APIRouter, UploadFile, File
from app.services.pdf_processor import pdf_to_images
from app.services.ocr_service import perform_ocr
from app.services.ocr_cleaner import clean_ocr_text
from app.services.answer_parser import parse_answers
import os
import json
from datetime import datetime



router = APIRouter()


@router.post("/upload-answer-pdf")
async def upload_answer_pdf(file: UploadFile = File(...)):
    pdf_bytes = await file.read()
    images = pdf_to_images(pdf_bytes)

    extracted_text_pages = []

    # Create folder for this upload
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = f"ocr_outputs/upload_{timestamp}"
    os.makedirs(output_dir, exist_ok=True)

    total_pages = len(images)

    for idx, img in enumerate(images):
        print(f"OCR processing page {idx+1}/{total_pages}", flush=True)

        raw_text = perform_ocr(img)
        
        # Post-process to clean strikethrough artifacts
        text = clean_ocr_text(raw_text)

        page_data = {
            "page": idx + 1,
            "text": text
        }

        extracted_text_pages.append(page_data)

        # Save per-page text (cleaned)
        with open(f"{output_dir}/page_{idx+1:02d}.txt", "w", encoding="utf-8") as f:
            f.write(text)

    # Save combined JSON
    with open(f"{output_dir}/raw_pages.json", "w", encoding="utf-8") as f:
        json.dump(extracted_text_pages, f, indent=2, ensure_ascii=False)

    structured_answers = parse_answers(extracted_text_pages)

    return {
        "status": "success",
        "ocr_saved_to": output_dir,
        "structured_answers": structured_answers
    }


