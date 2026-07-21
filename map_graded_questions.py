
import sys
import os
import re
import json
import fitz  # PyMuPDF
from PIL import Image
import io
import pytesseract
from pytesseract import Output

# Configuration
PDF_PATH = "/Users/gaureshmantri/Desktop/CheckerAI/AS 8 NORMAL Handwriting + Practical 2764.pdf"
GRADING_FILE = "CheckerAI - Backend/grading_results/grading_final.json"
OUTPUT_JSON = "mapped_coordinates.json"

# Known Page Ranges (Hardcoding relevant ranges from our previous fix to help search)
# This reduces false positives (e.g. finding "a)" in the wrong section)
PAGE_HINTS = {
    "SectionA": {
        "Q1": [2, 3],
        "Q2": [4, 5, 6, 7, 8, 9, 10, 11] # Wide range
    },
    "SectionB": {
        "Q1": [11, 12, 13, 14]
    }
}

def load_targets(json_path):
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    targets = []
    
    # Extract structural targets
    # We want: Section -> Q -> SubQ
    gradeds = data.get("graded_answers", {})
    
    for sec_name, sec_data in gradeds.items():
        for q_name, q_data in sec_data.items():
            # Create a target object for the Main Question
            # Markers: "Q.1", "Q1", "1)"
            # Note: Section B Q1 is often labeled "3)" or "Division B" in this specific paper
            
            main_patterns = [
                rf"Q\.?{q_name.replace('Q','')}\)", # Q.1)
                rf"{q_name.replace('Q','')}\)",     # 1)
                rf"^{q_name.replace('Q','')}\s"     # 1 ...
            ]
            
            # Special case hacks for this specific known user issue
            if sec_name == "SectionB" and q_name == "Q1":
                main_patterns += [r"Division\s*B", r"3\)"]

            q_obj = {
                "id": f"{sec_name}-{q_name}",
                "section": sec_name,
                "question": q_name,
                "main_patterns": main_patterns,
                "subquestions": []
            }
            
            # Find subquestions
            for sub_k, sub_v in q_data.items():
                if isinstance(sub_v, dict) and "marks_obtained" in sub_v:
                    # Leaf node (actual subquestion)
                    # Pattern: "a)", "b)", "(a)"
                    sub_patterns = [
                        rf"{sub_k}\)",       # a)
                        rf"\({sub_k}\)",     # (a)
                        rf"^{sub_k}\s"       # a ...
                    ]
                    q_obj["subquestions"].append({
                        "id": sub_k,
                        "patterns": sub_patterns
                    })
                elif isinstance(sub_v, dict) and "a" in sub_v: 
                     # Nested 'a' -> 'a' case
                     sub_patterns = [rf"a\)", rf"\(a\)"]
                     q_obj["subquestions"].append({
                        "id": "a", 
                        "patterns": sub_patterns
                     })

            targets.append(q_obj)
            
    return targets

def find_in_page_words(words, patterns):
    """
    Search a list of Tesseract words for regex patterns.
    Returns: (text, bbox: [x,y,w,h])
    """
    # Join words slightly to allow matching "Q. 1" across word boundaries?
    # Tesseract 'words' are split by space.
    # Simple check: Check individual match first.
    
    for i, w in enumerate(words):
        txt = w['text']
        for pat in patterns:
            if re.search(pat, txt, re.IGNORECASE):
                return txt, [w['left'], w['top'], w['width'], w['height']]
                
    return None, None

def main():
    print("--- Mapping Graded Questions to Coordinates ---")
    
    targets = load_targets(GRADING_FILE)
    print(f"Loaded {len(targets)} Main Questions targets.")
    
    doc = fitz.open(PDF_PATH)
    final_map = {}
    
    for target in targets:
        sec = target['section']
        q = target['question']
        print(f"\nProcessing {sec} {q}...")
        
        # Determine Page Scope
        start_page_hint = 1
        end_page_hint = len(doc)
        
        if sec in PAGE_HINTS and q in PAGE_HINTS[sec]:
            rng = PAGE_HINTS[sec][q]
            start_page_hint = rng[0]
            end_page_hint = rng[-1]
            
        print(f"  Searching Pages {start_page_hint}-{end_page_hint}...")
        
        found_main = False
        main_coords = None
        main_page = None
        
        # 1. FIND MAIN QUESTION
        # Iterate pages in range
        for p_idx in range(start_page_hint - 1, end_page_hint):
            if found_main: break
            
            page = doc.load_page(p_idx)
            page_num = p_idx + 1
            
            # OCR Prep
            mat = fitz.Matrix(2, 2)
            pix = page.get_pixmap(matrix=mat)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            
            # Get Words
            data = pytesseract.image_to_data(img, output_type=Output.DICT)
            words = []
            n = len(data['text'])
            for i in range(n):
                if data['text'][i].strip():
                    words.append({
                        'text': data['text'][i], 
                        'left': data['left'][i], 
                        'top': data['top'][i], 
                        'width': data['width'][i], 
                        'height': data['height'][i]
                    })
            
            # Search Main Patterns
            txt, box = find_in_page_words(words, target['main_patterns'])
            
            if txt:
                print(f"  [FOUND MAIN] '{txt}' on Page {page_num}")
                
                # Scale Coords
                scale_x = page.rect.width / pix.width
                scale_y = page.rect.height / pix.height
                
                pdf_box = [
                    round(box[0] * scale_x, 1),
                    round(box[1] * scale_y, 1),
                    round(box[2] * scale_x, 1),
                    round(box[3] * scale_y, 1)
                ]
                
                main_coords = pdf_box
                main_page = page_num
                found_main = True
                
                final_map[target['id']] = {
                    "page": page_num,
                    "bbox": pdf_box,
                    "text": txt,
                    "sub_questions": {}
                }
                
                # 2. FIND SUBQUESTIONS (SEQUENTIAL from here)
                # We assume SubQs follow MainQ on same or subsequent pages
                
                # Remaining words on THIS page
                # Filter for words below the main match (y > box[1])
                upcoming_words = [w for w in words if w['top'] > box[1]]
                
                for sub in target['subquestions']:
                    sub_id = sub['id']
                    # Try current page
                    s_txt, s_box = find_in_page_words(upcoming_words, sub['patterns'])
                    
                    if s_txt:
                        print(f"    [FOUND SUB {sub_id}] '{s_txt}' on Page {page_num}")
                        # Scale
                        s_pdf_box = [
                            round(s_box[0] * scale_x, 1),
                            round(s_box[1] * scale_y, 1),
                            round(s_box[2] * scale_x, 1),
                            round(s_box[3] * scale_y, 1)
                        ]
                        final_map[target['id']]["sub_questions"][sub_id] = {
                            "page": page_num,
                            "bbox": s_pdf_box,
                            "text": s_txt
                        }
                    else:
                        # Scan next few pages?
                        pass

    # Save
    with open(OUTPUT_JSON, "w") as f:
        json.dump(final_map, f, indent=2)
    print(f"\nSaved map to {OUTPUT_JSON}")

if __name__ == "__main__":
    main()
