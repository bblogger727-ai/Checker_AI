import json
import os
import re
from app.services.answer_aligner import align_answers_to_schema
from app.services.answer_grader import grade_all_answers

def parse_ocr_text(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read()

    # If file has PAGE markers, split them
    page_pattern = r'========== PAGE (\d+) =========='
    parts = re.split(page_pattern, text)
    
    pages = []
    
    if len(parts) > 1:
        # Parts [0] is pre-text (empty), [1] is page number, [2] is content, [3] is page number...
        # Loop with step 2
        for i in range(1, len(parts), 2):
            page_num = int(parts[i])
            content = parts[i+1].strip()
            if content:
                pages.append({"page": page_num, "text": content})
    else:
        # Treat as single page
        if text.strip():
            pages.append({"page": 1, "text": text})
            
    print(f"Parsed {len(pages)} pages from OCR text.")
    return pages

def main():
    base_dir = "/app"
    
    # Paths
    ocr_path = os.path.join(base_dir, "pipeline_temp/4_ocr_output.txt")
    schema_path = os.path.join(base_dir, "question_schemas/schema_repaired.json")
    model_answers_path = os.path.join(base_dir, "question_schemas/model_answers_final.json")
    
    aligned_output_path = os.path.join(base_dir, "pipeline_temp/aligned_answers_final.json")
    grading_output_path = os.path.join(base_dir, "grading_results/grading_final.json")
    
    # 1. Align Answers
    print("--- 1. Aligning Answers ---")
    if os.path.exists(aligned_output_path) and os.path.getsize(aligned_output_path) > 0:
        print(f"Aligned answers found at {aligned_output_path}. Skipping alignment.")
        with open(aligned_output_path, "r", encoding="utf-8") as f:
            aligned_answers = json.load(f)
    else:
        student_pages = parse_ocr_text(ocr_path)
        
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
            
        print("Running alignment...")
        aligned_answers = align_answers_to_schema(student_pages, schema)
        
        with open(aligned_output_path, "w", encoding="utf-8") as f:
            json.dump(aligned_answers, f, indent=2, ensure_ascii=False)
        print(f"Aligned answers saved to {aligned_output_path}")
    
    # 2. Grade Answers
    print("\n--- 2. Grading Answers ---")
    with open(model_answers_path, "r", encoding="utf-8") as f:
        model_answers = json.load(f)
        
    print("Running grading...")
    results = grade_all_answers(aligned_answers, model_answers)
    
    # Ensure dir exists
    os.makedirs(os.path.dirname(grading_output_path), exist_ok=True)
    with open(grading_output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
        
    print(f"Grading results saved to {grading_output_path}")
    print("Done!")

if __name__ == "__main__":
    main()
