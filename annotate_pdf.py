
import sys
import os
import json
import fitz  # PyMuPDF

# Configuration
PDF_PATH = "/Users/gaureshmantri/Desktop/CheckerAI/FR AS 14865 .pdf"
GRADING_FILE = "CheckerAI - Backend/grading_results/grading_final.json"
COORDS_FILE = "final_coordinates.json"
OUTPUT_PDF = "CheckerAI - Backend/grading_results/FR_14865_annotated.pdf"

def load_json(path):
    if not os.path.exists(path):
        print(f"Error: File not found {path}")
        return {}
    with open(path, 'r') as f:
        return json.load(f)

def main():
    print("--- Annotating Student PDF ---")
    
    grading_data = load_json(GRADING_FILE)
    coords_map = load_json(COORDS_FILE)
    
    if not grading_data:
        return

    doc = fitz.open(PDF_PATH)
    
    # 1. Flatten Grading Data to match Coords Keys (Section-Q)
    # We also need to handle MCQs which might be grouped
    
    graded_answers = grading_data.get("graded_answers", {})
    
    for sec, sec_data in graded_answers.items():
        for q, q_data in sec_data.items():
            target_id = f"{sec}-{q}"
            
            # Determine Score & Status
            marks_obtained = 0
            marks_total = 0
            symbol = "?"
            
            # Logic: Recursively find 'marks_obtained' in nested dicts if needed
            # But based on grading_final.json structure:
            # Practical: SectionA -> Q1 -> a -> marks_obtained
            # MCQ: SectionA -> MCQ -> 1 -> marks_obtained
            
            # Helper to find leaf
            def find_marks(d):
                if "marks_obtained" in d:
                    return d
                for k, v in d.items():
                    if isinstance(v, dict):
                        res = find_marks(v)
                        if res: return res
                return None

            leaf = find_marks(q_data)
            
            if leaf:
                marks_obtained = float(leaf.get("marks_obtained", 0))
                marks_total = float(leaf.get("marks_total", 0))
                
                # Visual Logic
                # If it's MCQ (usually 1 or 2 marks total), use Ticks/Cross
                # If it's Practical (larger marks), use Score Text
                
                is_mcq = "MCQ" in target_id or marks_total <= 2.0
                
                if is_mcq:
                    if marks_obtained == marks_total and marks_total > 0:
                        symbol = "TICK"
                    elif marks_obtained == 0:
                        symbol = "CROSS"
                    else:
                        symbol = "SCORE" # Partial MCQ?
                else:
                    symbol = "SCORE"

            # 2. Find Location
            page_num = 0 
            rect = None
            
            coord_info = coords_map.get(target_id)
            if coord_info and coord_info.get("status") == "found":
                page_num = coord_info["page"]
                c = coord_info["bbox"]
                rect = fitz.Rect(c[0], c[1], c[0]+c[2], c[1]+c[3])
            elif coord_info and "page" in coord_info and coord_info["page"]:
                # Fallback: Top Left of identified page
                page_num = coord_info["page"]
                # Adjusted to be slightly lower to avoid header
                rect = fitz.Rect(50, 80, 150, 110) 
            
            # 3. Draw Annotation
            # Fallback for MCQs specifically if coords missing
            if page_num == 0:
                if "SectionA" in target_id: 
                    page_num = 1
                    rect = fitz.Rect(50, 100, 150, 130) # Default A Box
                elif "SectionB" in target_id: 
                    page_num = 11
                    rect = fitz.Rect(50, 100, 150, 130) # Default B Box

            if 1 <= page_num <= len(doc):
                page = doc.load_page(page_num - 1)
                
                # Colors
                RED = (1, 0, 0)
                
                # Draw Box/Mark
                if symbol == "TICK":
                    # Red Tick (User requested "Red ink")
                    # Draw Checkmark path
                    p = fitz.Point(rect.tl)
                    page.draw_line(p + (0, 10), p + (5, 15), color=RED, width=2.5)
                    page.draw_line(p + (5, 15), p + (15, 0), color=RED, width=2.5)
                    # Text score next to it?
                    # page.insert_text(rect.tl + (20, 0), f"{marks_obtained}", fontsize=12, color=RED)
                elif symbol == "CROSS":
                    # Red Cross
                    p = fitz.Point(rect.tl)
                    page.draw_line(p, p + (12, 12), color=RED, width=2.5)
                    page.draw_line(p + (12, 0), p + (0, 12), color=RED, width=2.5)
                    # page.insert_text(rect.br + (5, 0), "0", fontsize=12, color=RED)
                else:
                    # Score text (Just the number, e.g. "3.5")
                    # Draw a small circle/box around it
                    center = rect.tl + (20, 10)
                    page.draw_circle(center, 18, color=RED, width=1.5)
                    page.insert_text(center + (-8, 4), f"{marks_obtained}", fontsize=14, color=RED)
                
                print(f"Annotated {target_id} on Page {page_num} ({symbol}) -> Score: {marks_obtained}")
            else:
                print(f"Skipping {target_id} (Page {page_num} invalid)")

    # Save
    doc.save(OUTPUT_PDF)
    print(f"\nSaved annotated PDF: {OUTPUT_PDF}")

if __name__ == "__main__":
    main()
