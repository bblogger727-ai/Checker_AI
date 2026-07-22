"""
Single Question OCR Service

For the single-question feedback mode:
- Question + Model Answer images → OCR'd by OpenAI GPT-4o-mini (cheap, straightforward)
- Student Answer image → OCR'd by Anthropic Claude (better for handwriting)
"""

import os
import base64
import json
import re
import anthropic
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, max_retries=10)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

CLAUDE_MODEL = "claude-sonnet-4-6"
OPENAI_CHEAP_MODEL = "gpt-4o-mini"  # cheapest vision-capable model


def _encode_image(image_path: str) -> tuple[str, str]:
    """Return (base64_data, media_type) for a given image path."""
    ext = os.path.splitext(image_path)[1].lower()
    media_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    media_type = media_type_map.get(ext, "image/jpeg")
    with open(image_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    return data, media_type


def ocr_question_and_model_answer(question_img_path: str, model_answer_img_path: str) -> dict:
    """
    Use OpenAI GPT-4o-mini to extract text from the question and model answer images.
    Returns a dict: {"question_text": "...", "model_answer": "..."}
    """
    print(f"[OCR] Extracting question from: {question_img_path}", flush=True)
    print(f"[OCR] Extracting model answer from: {model_answer_img_path}", flush=True)

    q_data, q_type = _encode_image(question_img_path)
    ma_data, ma_type = _encode_image(model_answer_img_path)

    prompt = """You are an OCR assistant for a CA (Chartered Accountancy) exam paper.
You are given TWO images:
1. First image: The QUESTION being asked.
2. Second image: The MODEL ANSWER (official solution) for that question.

Extract the full text from BOTH images exactly as written.

Return a JSON object with:
{
  "question_text": "Complete question text from image 1",
  "model_answer": "Complete model answer text from image 2"
}

CRITICAL RULES:
- Preserve all tables, calculations, and formatting as closely as possible in text form.
- Do NOT add any commentary — just extract the text.
- Do NOT skip any text.
"""

    response = openai_client.chat.completions.create(
        model=OPENAI_CHEAP_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{q_type};base64,{q_data}"}},
                    {"type": "image_url", "image_url": {"url": f"data:{ma_type};base64,{ma_data}"}},
                ],
            }
        ],
        response_format={"type": "json_object"},
        max_tokens=4096,
        temperature=0,
    )

    raw = response.choices[0].message.content.strip()
    result = json.loads(raw)
    print(f"[OCR] Question extracted ({len(result.get('question_text',''))} chars)", flush=True)
    print(f"[OCR] Model answer extracted ({len(result.get('model_answer',''))} chars)", flush=True)
    return result


def ocr_student_answer(student_answer_img_paths: list[str]) -> str:
    """
    Use Claude to extract the student's handwritten answer from one or multiple images sequentially.
    Returns the extracted text as a single string.
    """
    print(f"[OCR] Extracting student answer from {len(student_answer_img_paths)} images...", flush=True)

    content = []
    
    for path in student_answer_img_paths:
        sa_data, sa_type = _encode_image(path)
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": sa_type, "data": sa_data},
        })
        
    content.append({
        "type": "text",
        "text": "Extract the complete text of this student's handwritten answer from the provided image(s). Read them in order. Include all working steps, tables, and calculations exactly as written. Return only the extracted text, no commentary.",
    })

    response = claude_client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system="You are an expert OCR system specialised in reading handwritten CA exam answer sheets. Extract all the text exactly as written, preserving tables and calculations.",
        messages=[
            {
                "role": "user",
                "content": content,
            }
        ],
        temperature=0,
    )

    text = response.content[0].text.strip()
    print(f"[OCR] Student answer extracted ({len(text)} chars)", flush=True)
    return text

