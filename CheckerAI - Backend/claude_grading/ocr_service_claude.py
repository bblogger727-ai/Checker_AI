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

SYSTEM_PROMPT = """You are an OCR engine. Extract all handwritten English text, equations, tables, and numbers accurately.

FORMATTING & PLAIN TEXT RULES:
- Output clean plain text or standard markdown only.
- NEVER use HTML entities (such as &nbsp;, &ensp;, &emsp;, etc.) or HTML tags under any circumstances. Use plain text spaces.
- Transcribe mathematical equations as natural, readable plain text (e.g. (1 + 4.20%)^2 (1+r) = (1 + 4.48%)^3).

SPATIAL LAYOUT:
- Reproduce the text line-by-line in logical reading order.
- Each handwritten line should be a line in your output.
- Preserve blank lines between sections.
- Words on the same handwritten line must stay on the same output line.
- Do NOT repeat whitespace characters or formatting tokens.

PRESERVE: numbers, formulas, tables, headings, question numbers. Do not miss any.

QUESTION / ANSWER LABEL NORMALIZATION (CRITICAL):
- Students write headings at the top of each answer such as "Ans 7(a)", "Q.2 b)", "Answer 3", etc.
- These labels are often handwritten quickly and may be OCR'd incorrectly. Common errors:
  * The word "Ans" may appear as: "An", "Ans.", "Aug", "Quy", "Day", "ay", "Key", "Try", "an", "Aug."
  * The letter "Q" (for Question) may appear as: "0", "Qu", "Quy", "Q."
  * Numbers can be misread: "7" → "9", "1" → "l" or "I", "8" → "B"
  * Parentheses may be missing or misread: "(a)" → "a", "la", "(9)"
- When you see any heading at the top of an answer block that LOOKS LIKE a question label, output it in the STANDARD FORMAT: "Ans X(y)" where X is the question number and y is the sub-part letter.
  * Examples: "[day 7. (9)]" → "Ans 7(a)", "[Quy 7 (b)]" → "Ans 7(b)", "[aug 8 (b)]" → "Ans 8(b)", "[Try (1)(a)]" → "Ans 1(a)", "Day 2 (a)" → "Ans 2(a)", "Key 2(b)" → "Ans 2(b)"
- Context clues: if text following the label is clearly an ANSWER (paragraphs, calculations, tables), the heading IS a question label.
- If you cannot determine the question number confidently, output the label exactly as written — do NOT guess.

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
- Be extremely careful with currency symbols (₹, $, £).
- Be careful with 'S' which might look like '5'."""

USER_TEXT = (
    "Extract all handwritten text, formulas, and numbers from this answer sheet image as clean plain text. "
    "No words on the page should be missed or changed. "
    "There might be words or numbers that are scratched or crossed out — remove just those words. "
    "Draw tables and all their contents appropriately. "
    "Maintain the layout line-by-line using plain text. Do NOT use HTML entities like &nbsp;."
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
                import re
                # Safety net: Clean any stray HTML entities or runaway whitespace loops
                text = re.sub(r'&nbsp;|&#160;|&ensp;|&emsp;', ' ', text)
                text = re.sub(r'[ \t]{8,}', '   ', text)
                return text.strip()
            
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
    import fitz
    from PIL import Image
    
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    print(f"[Claude OCR] {total_pages} pages found.", flush=True)

    page_texts = []
    for page_num in range(total_pages):
        print(f"[Claude OCR]   Page {page_num+1}/{total_pages}...", flush=True)
        page = doc[page_num]
        pix = page.get_pixmap(dpi=dpi)
        
        # Convert fitz pixmap to PIL Image
        mode = "RGBA" if pix.alpha else "RGB"
        img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
        
        # We need RGB for Claude OCR API
        if img.mode != "RGB":
            img = img.convert("RGB")
            
        text = perform_ocr_claude(img)
        page_texts.append(f"=== Page {page_num+1} ===\n{text}")
        print(f"[Claude OCR]   → {len(text)} chars extracted", flush=True)
    
    doc.close()

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
