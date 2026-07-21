
import sys
import os
import re
import json
import fitz  # PyMuPDF
from PIL import Image
import io
import pytesseract
from pytesseract import Output
import difflib

# Configuration
PDF_PATH = "/Users/gaureshmantri/Desktop/CheckerAI/FR AS 14865 .pdf"
OCR_FILE = "CheckerAI - Backend/pipeline_temp/3_ocr_output.txt"
GRADING_FILE = "CheckerAI - Backend/grading_results/grading_final.json"
OUTPUT_JSON = "final_coordinates.json"

# Fuzzy Patterns for Tesseract Matching
# Mapping Question IDs to potential OCR text representations
PATTERNS = {
    "SectionA-Q1": [r"Q\.?1", r"1\)", r"Q1", r"O\.1", r"0\.1"],
    "SectionA-Q2": [r"Q\.?2", r"2\)", r"Q2", r"O\.2", r"0\.2", r"22\)"], # 22) seen in logs
    "SectionA-Q3": [r"Q\.?3", r"3\)", r"Q3", r"093\)"],
    "SectionA-Q4": [r"Q\.?4", r"4\)", r"Q4"],
    "SectionA-Q5": [r"Q\.?5", r"5\)", r"Q5"],
    "SectionA-Q6": [r"Q\.?6", r"6\)", r"Q6"],
    "SectionA-Q7": [r"Q\.?7", r"7\)", r"Q7"],
    "SectionB-Q1": [r"Division\s*B", r"3\)", r"Q\.?3", r"Qwisioa"], # 3) used for Sec B Q1
}

def load_grading_targets():
    """Extracts list of questions to find from grading_final.json"""
    targets = []
    if not os.path.exists(GRADING_FILE):
        print(f"Grading file not found: {GRADING_FILE}")
        return targets

    with open(GRADING_FILE, 'r') as f:
        data = json.load(f)

    # Simplified extraction of Main Questions for now
    gradeds = data.get("graded_answers", {})
    for sec, sec_data in gradeds.items():
        for q, q_data in sec_data.items():
            # ID: SectionA-Q1
            targets.append(f"{sec}-{q}")
    return targets

def parse_cached_ocr_pages():
    """Parses 3_ocr_output.txt to get content per page"""
    if not os.path.exists(OCR_FILE):
        print(f"OCR file not found: {OCR_FILE}")
        return {}

    with open(OCR_FILE, 'r') as f:
        text = f.read()

    pages = {}
    parts = re.split(r'===\s*Page\s+(\d+)\s*===', text)
    for i in range(1, len(parts), 2):
        if parts[i].isdigit():
            p_num = int(parts[i])
            content = parts[i+1]
            pages[p_num] = content
    return pages

def find_page_from_cached_ocr(qid, pages_content):
    """
    Determines the Page Number using the reliable Cached OCR.
    """
    # Define regex for finding the START of the question in plain text
    # This is "easier" than Tesseract because we have clean(er) text or known patterns
    
    # Defaults
    sec, q = qid.split("-")
    
    patterns = []
    # Use the flexible PATTERNS dict directly
    # This avoids strict overrides that fail on different student styles
    full_qid = f"{sec}-{q}"
    if full_qid in PATTERNS:
        patterns = PATTERNS[full_qid]
    else:
        # Fallback
        patterns = [rf"Q\.?{q.replace('Q','')}\)", rf"^{q.replace('Q','')}\)"]

    for p_num in sorted(pages_content.keys()):
        content = pages_content[p_num]
        for pat in patterns:
            if re.search(pat, content, re.IGNORECASE):
                return p_num
    return None

def find_bbox_on_page(page_num, qid, doc):
    """
    Runs Tesseract on the specific PDF page to find the bbox.
    STRATEGY: Crop to Left Margin (20% width) to reduce noise.
    """
    page = doc.load_page(page_num - 1) # 0-indexed
    
    # 2x Zoom for OCR
    mat = fitz.Matrix(2, 2)
    pix = page.get_pixmap(matrix=mat)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    
    width, height = img.size
    
    # Define Margin (Left 20%)
    margin_width = int(width * 0.25) # Increased to 25% to be safe
    margin_img = img.crop((0, 0, margin_width, height))
    
    # OCR on Margin
    data = pytesseract.image_to_data(margin_img, output_type=Output.DICT)
    
    # Search patterns
    patterns = PATTERNS.get(qid, [rf"Q\.?{qid.split('-')[1].replace('Q','')}\)"])
    
    # Also add generous fallbacks for "1)", "2)" etc if QID is "Q1"
    parts = qid.split("-")
    if len(parts) > 1:
        q_num = parts[1].replace("Q", "")
        if q_num.isdigit():
             patterns.append(rf"^{q_num}\)")
             patterns.append(rf"Q\.?{q_num}")

    # Iterate words
    n = len(data['text'])
    for i in range(n):
        text = data['text'][i].strip()
        if not text: continue
        
        for pat in patterns:
            # Fuzzy match?
            if re.search(pat, text, re.IGNORECASE):
                # Found match!
                x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                
                # Scale back
                # Note: Coordinate X is correct because we cropped from 0
                # If we cropped from middle, we'd add offset.
                
                scale_x = page.rect.width / pix.width
                scale_y = page.rect.height / pix.height
                
                found_box = [
                    round(x * scale_x, 1),
                    round(y * scale_y, 1),
                    round(w * scale_x, 1),
                    round(h * scale_y, 1)
                ]
                found_text = text
                return found_box, found_text
                
    return None, None

def main():
    print("--- Hybrid Coordinate Extraction ---")
    
    # 1. Load Data
    targets = load_grading_targets()
    pages_content = parse_cached_ocr_pages()
    doc = fitz.open(PDF_PATH)
    
    results = {}
    
    print(f"Processing {len(targets)} targets: {targets}")
    
    for qid in targets:
        # 2. Find Page (Cached OCR)
        page_num = find_page_from_cached_ocr(qid, pages_content)
        
        if not page_num:
            print(f"[{qid}] Page NOT found in Cached OCR.")
            results[qid] = {"status": "page_not_found"}
            continue
            
        print(f"[{qid}] Found on Page {page_num} (Cached OCR). Scanning for coordinates...")
        
        # 3. Find Coords (Tesseract)
        bbox, text = find_bbox_on_page(page_num, qid, doc)
        
        if bbox:
            print(f"  -> MATCH: '{text}' at {bbox}")
            results[qid] = {
                "status": "found",
                "page": page_num,
                "bbox": bbox,
                "text": text
            }
        else:
             print(f"  -> Coordinates NOT found on Page {page_num} (Tesseract noise?)")
             results[qid] = {
                 "status": "bbox_not_found", 
                 "page": page_num
             }

    # Save
    with open(OUTPUT_JSON, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nFinal map saved to {OUTPUT_JSON}")

if __name__ == "__main__":
    main()
