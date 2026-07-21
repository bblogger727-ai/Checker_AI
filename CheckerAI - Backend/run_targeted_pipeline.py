import sys, os, json, time

BASE_DIR = '/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend'
sys.path.insert(0, BASE_DIR)

from claude_grading.model_answer_builder_claude import build_model_answers_claude
from run_pipeline_claude import run_stage_4_claude, run_stage_5_claude
from app.services.model_answer_builder import extract_pdf_text_tesseract

# Setup source data (cached schema and OCR) and destination
DATASET_SRC = os.path.join(BASE_DIR, "grading_results/dataset_15166_claude")
DATASET_DEST = os.path.join(BASE_DIR, "grading_results/dataset_15166_final")
os.makedirs(DATASET_DEST, exist_ok=True)

print("=== ZERO WASTE PIPELINE ===")

# 1. Load Schema
schema_path = os.path.join(DATASET_SRC, "schema_with_answers.json")
if not os.path.exists(schema_path):
    # Fallback to older 15166 dataset if needed
    schema_path = os.path.join(BASE_DIR, "grading_results/dataset_15166/schema_with_answers.json")

print(f"Loading cached schema from: {schema_path}")
with open(schema_path) as f:
    schema = json.load(f)

# Clean schema model answers just in case they are polluted
def clean_schema(node):
    if not isinstance(node, dict): return
    if 'model_answer' in node: node['model_answer'] = ''
    for k,v in node.items():
        if isinstance(v, dict): clean_schema(v)
clean_schema(schema)

# 2. Stage 2: Model Answers (Claude)
sa_path = '/Users/gaureshmantri/Desktop/CheckerAI/15166sa.pdf'
print("\n--- STAGE 2: Model Answer Extraction ---")
# Extract SA Text locally (Tesseract)
sa_text = extract_pdf_text_tesseract(sa_path)
schema_with_answers = build_model_answers_claude(schema, sa_text, sa_path)

swa_path = os.path.join(DATASET_DEST, "schema_with_answers.json")
with open(swa_path, "w") as f:
    json.dump(schema_with_answers, f, indent=2, ensure_ascii=False)
print(f"Saved to {swa_path}")

# 3. Stage 4: Alignment (Claude)
print("\n--- STAGE 4: Answer Alignment ---")
ocr_path = os.path.join(DATASET_SRC, "ocr_output.txt")
if not os.path.exists(ocr_path):
    ocr_path = os.path.join(BASE_DIR, "grading_results/dataset_15166/ocr_output.txt")
    
print(f"Loading cached OCR from: {ocr_path}")
with open(ocr_path) as f:
    ocr_text = f.read()

# Debug Question 3 model answer
q3_ma = schema_with_answers.get('SectionA', {}).get('Q3', {}).get('model_answer', '')
print(f"DEBUG: Q3 Model Answer is {len(q3_ma)} chars.")
if len(q3_ma) < 100:
    print(f"Q3 CONTENT: '{q3_ma}'")

aligned_answers = run_stage_4_claude(schema_with_answers, ocr_text)
aligned_path = os.path.join(DATASET_DEST, "aligned_answers.json")
with open(aligned_path, "w") as f:
    json.dump(aligned_answers, f, indent=2, ensure_ascii=False)
print(f"Saved to {aligned_path}")

# 4. Stage 5: Grading (Claude)
print("\n--- STAGE 5: Grading ---")
import claude_grading.answer_grader_claude as grader
grading_results = grader.grade_all_answers(aligned_answers, aligned_answers)
grading_path = os.path.join(DATASET_DEST, "grading_final.json")
with open(grading_path, "w") as f:
    json.dump(grading_results, f, indent=2, ensure_ascii=False)
print(f"Saved to {grading_path}")

print("\n=== PIPELINE COMPLETE ===")
