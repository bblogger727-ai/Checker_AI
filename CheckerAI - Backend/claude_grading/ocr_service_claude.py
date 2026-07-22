"""
Claude OCR Service — Alternative to GPT-4o Vision OCR.

Uses the same prompt and pipeline structure as ocr_service.py,
but calls Claude claude-sonnet-4-6 (via base64 image) instead of GPT-4o.

Usage:
    from claude_grading.ocr_service_claude import perform_ocr_claude, ocr_pdf_claude
"""

import base64
import io
import os
import sys
import time
from pdf2image import convert_from_path

import anthropic
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
CLAUDE_MODEL = "claude-sonnet-4-6"

# ------------------------------------------------------------------
# Core OCR function (mirrors perform_ocr in ocr_service.py)
# ------------------------------------------------------------------

SYSTEM_PROMPT = """You are an OCR engine. Extract all handwritten English text and numbers accurately.

SPATIAL LAYOUT (CRITICAL):
- Reproduce the text with exactly the same spatial arrangement as it appears on the page.
- Each line of handwriting must become exactly one line in your output.
- If the student left a blank line or large gap between sections, preserve that gap with a blank line in the output.
- Words on the same handwritten line must stay on the same output line.
- Do NOT merge multiple lines into one or split one line into multiple lines.
- The vertical position of text in your output should mirror the vertical position in the image as closely as possible.

PRESERVE: numbers, formulas, tables, headings, question numbers. Do not miss any.

STRIKETHROUGH DETECTION (CRITICAL):
- Words/numbers with HORIZONTAL LINES drawn through them are CANCELLED.
- SCRIBBLES or messy cross-outs are also CANCELLED.
- If a student wrote an answer and then crossed it out, ONLY transcribe the final valid answer.
- COMPLETELY OMIT cancelled/crossed-out/scribbled text from output.
- If uncertain, err on the side of omitting it.

TABLE EXTRACTION:
- Extract ALL numbers from tables — look at left AND right columns.
- Use markdown table format to preserve structure.

MANDATORY DATA EXTRACTION RULES:
- Extract absolutely ALL figures, numbers, tables, and symbols EXACTLY as written. Do not skip any numbers.
- Be extremely careful with the Indian Rupee symbol (₹) which might look like the number '2' or '£'. Do your best to interpret it correctly.
- Be careful with 'S' which might look like '5'."""

USER_TEXT = (
    "Extract all handwritten text and numbers from this answer sheet image. "
    "No words on the page should be missed or changed. "
    "There might be words or numbers that are scratched, like a line or multiple lines "
    "drawn through the middle of the word — remove just those words. "
    "Do not include them in the output. "
    "Draw tables and all their contents appropriately. "
    "IMPORTANT: Maintain the exact spatial layout of the page — each handwritten line "
    "must be its own line in the output, blank gaps between sections must be preserved "
    "as blank lines, and words on the same line must stay on the same line."
)


def image_to_base64(image: Image.Image) -> str:
    """
    Converts a PIL image to base64, ensuring it's under Claude's 5MB limit.
    Uses JPEG with iterative quality reduction and resizing if necessary.
    """
    # Convert to RGB if necessary (JPEG doesn't support transparency)
    if image.mode in ("RGBA", "P"):
        image = image.convert("RGB")
    
    # Claude's dimension limit: 8000px
    MAX_DIM = 8000
    if image.width > MAX_DIM or image.height > MAX_DIM:
        scale = MAX_DIM / max(image.width, image.height)
        new_size = (int(image.width * scale), int(image.height * scale))
        image = image.resize(new_size, Image.LANCZOS)
    
    # 5MB limit for Claude's base64 string. 
    # Base64 encoding increases size by ~33%, so raw binary must be < ~3.7MB.
    MAX_SIZE = int(3.5 * 1024 * 1024) 
    
    # Strategy 1: Iterative JPEG quality reduction
    quality = 95
    while quality >= 40:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
        if buffer.tell() <= MAX_SIZE:
            return base64.standard_b64encode(buffer.getvalue()).decode("utf-8")
        quality -= 10

    # Strategy 2: Iterative resizing + medium quality
    temp_img = image.copy()
    while temp_img.width > 1200 or temp_img.height > 1200:
        temp_img = temp_img.resize(
            (int(temp_img.width * 0.8), int(temp_img.height * 0.8)), 
            Image.LANCZOS
        )
        buffer = io.BytesIO()
        temp_img.save(buffer, format="JPEG", quality=75, optimize=True)
        if buffer.tell() <= MAX_SIZE:
            return base64.standard_b64encode(buffer.getvalue()).decode("utf-8")

    # Final fallback: Low quality, original size (or smallest resized)
    buffer = io.BytesIO()
    temp_img.save(buffer, format="JPEG", quality=30, optimize=True)
    return base64.standard_b64encode(buffer.getvalue()).decode("utf-8")


def perform_ocr_claude(image: Image.Image) -> str:
    """OCR a single PIL image using Claude vision."""
    image_b64 = image_to_base64(image)

    for attempt in range(2):
        try:
            print(f"[Claude OCR]   Attempt {attempt+1} for page OCR...", flush=True)
            response = claude_client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": image_b64,
                                },
                            },
                            {"type": "text", "text": USER_TEXT},
                        ],
                    }
                ],
                temperature=0 if attempt == 0 else 0.1
            )
            
            text = response.content[0].text.strip()
            if text:
                return text
            
            print(f"[Claude OCR]   Warning: Empty OCR text on attempt {attempt+1}.", flush=True)
            
        except Exception as e:
            print(f"[Claude OCR]   Attempt {attempt+1} failed: {e}", flush=True)
            if attempt == 0:
                time.sleep(2)
            else:
                return f"[OCR ERROR on this page: {e}]"
    
    return "[OCR ERROR: No text returned after 2 attempts]"


def ocr_pdf_claude(pdf_path: str, output_path: str | None = None, dpi: int = 200) -> str:
    """
    OCR an entire PDF using Claude, page by page.

    Returns the full OCR text in the same '=== Page N ===' format
    used by the rest of the pipeline.

    Args:
        pdf_path:    Path to the PDF file.
        output_path: Optional path to save the OCR text.  If None, not saved.
        dpi:         Resolution for PDF→image conversion (default 200).
    """
    print(f"[Claude OCR] Converting {pdf_path} to images at {dpi} DPI...", flush=True)
    images = convert_from_path(pdf_path, dpi=dpi)
    total_pages = len(images)
    print(f"[Claude OCR] {total_pages} pages found.", flush=True)

    page_texts = []
    for page_num, image in enumerate(images, start=1):
        print(f"[Claude OCR]   Page {page_num}/{total_pages}...", flush=True)
        text = perform_ocr_claude(image)
        page_texts.append(f"=== Page {page_num} ===\n{text}")
        print(f"[Claude OCR]   → {len(text)} chars extracted", flush=True)

    full_text = "\n\n".join(page_texts)

    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_text)
        print(f"[Claude OCR] Saved to {output_path}", flush=True)

    return full_text


# ------------------------------------------------------------------
# CLI entry-point: python ocr_service_claude.py <pdf_path> <output_path>
# ------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python ocr_service_claude.py <pdf_path> <output_txt_path>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    out_path = sys.argv[2]

    result = ocr_pdf_claude(pdf_path, output_path=out_path)
    total_chars = len(result)
    print(f"\n[Claude OCR] Done — {total_chars} total chars written to {out_path}")
