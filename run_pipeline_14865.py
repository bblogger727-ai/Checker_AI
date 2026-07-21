#!/usr/bin/env python3
"""Full pipeline runner for a single dataset — saves all outputs to a dataset-specific directory."""
import os, sys, json, re, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "CheckerAI - Backend"))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "CheckerAI - Backend", ".env"))

from app.core.openai_client import client
from app.services.pdf_extractor import extract_text_from_pdf
from app.services.model_answer_builder import build_model_answers
from app.services.answer_aligner import align_student_answers
from app.services.answer_grader import grade_all_answers

DATASET_ID = "14865"
BASE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(BASE, "CheckerAI - Backend")
PIPELINE_OUTPUT = os.path.join(BASE, "pipeline_output")
PIPELINE_TEMP = os.path.join(BACKEND, "pipeline_temp")
RESULTS_DIR = os.path.join(BACKEND, "grading_results", f"dataset_{DATASET_ID}")

QP_PATH = os.path.join(BASE, f"FR QP {DATASET_ID} .pdf")
SA_PATH = os.path.join(BASE, f"FR SA {DATASET_ID} .pdf")
AS_PATH = os.path.join(BASE, f"FR AS {DATASET_ID} .pdf")

os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs(PIPELINE_TEMP, exist_ok=True)
os.makedirs(PIPELINE_OUTPUT, exist_ok=True)

# ============================================================
# STAGE 1: Schema Generation
# ============================================================
print("=" * 60)
print("STAGE 1: Schema Generation")
print("=" * 60)

qp_text = extract_text_from_pdf(QP_PATH)
print(f"QP text length: {len(qp_text)} chars")

# Save QP text
qp_text_path = os.path.join(PIPELINE_TEMP, "1_qp_text.txt")
with open(qp_text_path, "w") as f:
    f.write(qp_text)

prompt = """You are given the text of a CA exam question paper (Financial Reporting).

Extract the question structure. For each question/subquestion, extract:
- question (full question text)
- marks (integer)
- or_group (null or string for OR alternatives, e.g. "or_A_1")

Return JSON with this structure:
{
  "SectionA": {
    "Q1": { "question": "...", "marks": 5, "or_group": null },
    "Q2": {
      "a": { "question": "...", "marks": 5, "or_group": null },
      "b": { "question": "...", "marks": 5, "or_group": null }
    }
  }
}

OR question detection: If questions are marked as alternatives (e.g., "Q1 OR Q1A"), 
assign the SAME or_group ID like "or_A_1".

Rules:
- Extract ONLY the question statements, NOT answers
- Preserve original numbering
- Output ONLY valid JSON
- Marks must be integers

Question Paper:
""" + qp_text

response = client.chat.completions.create(
    model='gpt-4o',
    messages=[
        {'role': 'system', 'content': 'You are a strict JSON generator for exam question schemas.'},
        {'role': 'user', 'content': prompt}
    ],
    response_format={"type": "json_object"},
    temperature=0
)

output = response.choices[0].message.content.strip()
schema = json.loads(output)

schema_path = os.path.join(PIPELINE_OUTPUT, "schema.json")
with open(schema_path, "w") as f:
    json.dump(schema, f, indent=2, ensure_ascii=False)
print(f"✓ Schema saved: {schema_path}")
print(f"  Sections: {list(schema.keys())}")

# ============================================================
# STAGE 2: Model Answer Extraction
# ============================================================
print("\n" + "=" * 60)
print("STAGE 2: Model Answer Extraction")
print("=" * 60)

# Use run_stage_2 which handles Tesseract OCR for tables
os.system(f'cd "{BACKEND}" && python3 run_stage_2_model_answers.py --sa "{SA_PATH}"')

# Load schema_with_answers
swa_path = os.path.join(PIPELINE_OUTPUT, "schema_with_answers.json")
with open(swa_path) as f:
    schema_with_answers = json.load(f)
print(f"✓ Schema with answers loaded from: {swa_path}")

# ============================================================
# STAGE 3: Student Answer OCR
# ============================================================
print("\n" + "=" * 60)
print("STAGE 3: Student Answer OCR")
print("=" * 60)

os.system(f'cd "{BACKEND}" && python3 run_stage_3_ocr.py --as "{AS_PATH}"')

# ============================================================
# STAGE 4: Alignment
# ============================================================
print("\n" + "=" * 60)
print("STAGE 4: Answer Alignment")
print("=" * 60)

os.system(f'cd "{BACKEND}" && python3 run_stage_4_alignment.py')

# Load aligned answers
aligned_path = os.path.join(PIPELINE_OUTPUT, "aligned_answers.json")
with open(aligned_path) as f:
    aligned = json.load(f)
print(f"✓ Aligned answers loaded from: {aligned_path}")

# ============================================================
# STAGE 5: Grading
# ============================================================
print("\n" + "=" * 60)
print("STAGE 5: Grading")
print("=" * 60)

grading_results = grade_all_answers(
    aligned_answers=aligned,
    model_answers=aligned
)

grading_path = os.path.join(RESULTS_DIR, "grading_final.json")
with open(grading_path, "w") as f:
    json.dump(grading_results, f, indent=2, ensure_ascii=False)

meta = grading_results.get("metadata", {})
print(f"✓ Grading saved: {grading_path}")
print(f"  Score: {meta.get('total_marks_obtained', 0)}/{meta.get('total_marks_possible', 0)}")
print(f"  Percentage: {meta.get('percentage', 0):.2f}%")

# Save aligned answers copy
import shutil
shutil.copy(aligned_path, os.path.join(RESULTS_DIR, "aligned_answers.json"))
shutil.copy(swa_path, os.path.join(RESULTS_DIR, "schema_with_answers.json"))
print(f"✓ Aligned answers and schema copies saved to: {RESULTS_DIR}")

print("\n" + "=" * 60)
print(f"PIPELINE COMPLETE FOR DATASET {DATASET_ID}")
print("=" * 60)
