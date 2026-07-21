"""
Solution Text Extractor with Hybrid OCR

Extracts text from solution PDFs. For pages with limited text (likely containing
images/tables that pdfplumber can't extract), sends them to OCR for proper extraction.
"""

import pdfplumber
import io
from pdf2image import convert_from_bytes
import base64
from app.core.openai_client import client


import hashlib
import os

# Minimum expected characters per page - pages with less are likely sparse/image-heavy
MIN_CHARS_PER_PAGE = 200


def ocr_page_image(image) -> str:
    """
    OCR a single page image using GPT-4o vision.
    Optimized for extracting text from CA exam solutions with tables.
    Includes caching to prevent redundant API calls.
    """
    # Convert PIL image to bytes for hashing and API
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    img_bytes = buffered.getvalue()
    
    # Compute hash for caching
    img_hash = hashlib.md5(img_bytes).hexdigest()
    cache_dir = "ocr_cache"
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f"{img_hash}.txt")
    
    # Check cache
    if os.path.exists(cache_path):
        print(f"[Solution OCR] Cache hit for image {img_hash[:8]}...", flush=True)
        with open(cache_path, "r", encoding="utf-8") as f:
            return f.read()

    # If not in cache, call API
    base64_image = base64.b64encode(img_bytes).decode('utf-8')
    
    prompt = """Extract ALL text from this CA exam solution page.

CRITICAL INSTRUCTIONS:
1. PRESERVE ALL TABLES - Format as markdown tables with | separators
2. Extract EVERY number accurately - numbers are critical for calculations
3. IGNORE any scratched/crossed-out text completely
4. Maintain the structure (headings, bullet points, numbered lists)
5. For computation tables, preserve all rows and columns

Output the extracted text ONLY, no commentary."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            temperature=0,
            max_tokens=4000  # Hard limit on generation
        )
        content = response.choices[0].message.content.strip()
        
        # Sanity check: A single page shouldn't be massive
        if len(content) > 25000:
             print(f"[Solution OCR] WARNING: OCR output too large ({len(content)} chars). Likely hallucination. Truncating.", flush=True)
             content = content[:25000] + "\n... [truncated]"
        
        # Save to cache
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        return content
    except Exception as e:
        print(f"[Solution OCR] Error: {e}", flush=True)
        return ""


def extract_solution_text(pdf_path: str) -> str:
    """
    Extract text from solution PDF with hybrid OCR for sparse pages.
    
    Pages with insufficient text (likely images/tables) are sent to OCR
    for proper extraction.
    """
    full_text = []
    pages_to_ocr = []
    page_texts = {}
    
    # First pass: Extract text with pdfplumber
    print("[Solution Extractor] First pass: Extracting text with pdfplumber...", flush=True)
    
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        
        for page_number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(layout=True)
            char_count = len(text.strip()) if text else 0
            
            if char_count < MIN_CHARS_PER_PAGE:
                # Sparse page - mark for OCR
                print(f"[Solution Extractor] Page {page_number}: {char_count} chars (SPARSE - will OCR)", flush=True)
                pages_to_ocr.append(page_number)
                page_texts[page_number] = None  # Placeholder
            else:
                print(f"[Solution Extractor] Page {page_number}: {char_count} chars", flush=True)
                page_texts[page_number] = text
    
    # Second pass: OCR sparse pages
    if pages_to_ocr:
        print(f"[Solution Extractor] Second pass: OCR for {len(pages_to_ocr)} sparse pages...", flush=True)
        
        # Read PDF bytes for image conversion
        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()
        
        # Convert sparse pages to images and OCR
        for page_num in pages_to_ocr:
            print(f"[Solution Extractor] OCR page {page_num}...", flush=True)
            
            # Convert single page to image
            images = convert_from_bytes(
                pdf_bytes,
                first_page=page_num,
                last_page=page_num,
                dpi=200
            )
            
            if images:
                ocr_text = ocr_page_image(images[0])
                page_texts[page_num] = ocr_text
                print(f"[Solution Extractor] Page {page_num} OCR: {len(ocr_text)} chars extracted", flush=True)
    
    # Combine all pages
    print("[Solution Extractor] Combining pages...", flush=True)
    for page_num in sorted(page_texts.keys()):
        text = page_texts[page_num]
        if text:
            full_text.append(f"\n\n========== PAGE {page_num} ==========\n\n")
            full_text.append(text)
    
    result = "\n".join(full_text)
    print(f"[Solution Extractor] Total: {len(result)} chars from {total_pages} pages ({len(pages_to_ocr)} OCR'd)", flush=True)
    
    return result
