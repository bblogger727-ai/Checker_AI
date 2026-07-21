#!/usr/bin/env python3
"""
Re-run Stage 4 (alignment) + Stage 5 (grading) for Paper 15155,
using the Claude OCR output (ocr_output_claude.txt) instead of GPT-4o OCR.
All earlier stages (1-3) are loaded from cache.
"""

import os, sys, json, shutil, time
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv()

DATASET_DIR   = os.path.join(BASE_DIR, "grading_results/dataset_15155")
PIPELINE_OUT  = os.path.join(BASE_DIR, "pipeline_output")
GRADING_RES   = os.path.join(BASE_DIR, "grading_results")

# ── Load cached schema_with_answers (Stage 1+2 already done) ─────────────────
swa_path = os.path.join(PIPELINE_OUT, "schema_with_answers.json")
with open(swa_path) as f:
    schema_with_answers = json.load(f)
print(f"[Setup] Loaded schema_with_answers from {swa_path}")

# ── Load CLAUDE OCR output ────────────────────────────────────────────────────
claude_ocr_path = os.path.join(DATASET_DIR, "ocr_output_claude.txt")
with open(claude_ocr_path) as f:
    ocr_text = f.read()
print(f"[Setup] Loaded Claude OCR from {claude_ocr_path} ({len(ocr_text)} chars)")

# ── STAGE 4: Claude Alignment ─────────────────────────────────────────────────
print("\n" + "="*60)
print("STAGE 4: Answer Alignment (CLAUDE SONNET 4) — using Claude OCR")
print("="*60)

from claude_grading.answer_aligner_claude import align_answers_to_schema_claude
import copy

pages = []
for block in ocr_text.split("=== Page "):
    if not block.strip():
        continue
    try:
        first_line, content = block.split("\n", 1)
        # first_line is like "1 ===" — strip the trailing "==="
        page_num = int(first_line.replace("===", "").strip())
        pages.append({"page": page_num, "text": content.strip()})
    except Exception as e:
        print(f"[Parse] Skipped block: {e}")

print(f"Parsed {len(pages)} pages from Claude OCR")

schema_copy = copy.deepcopy(schema_with_answers)
aligned = align_answers_to_schema_claude(pages, schema_copy)

aligned_path = os.path.join(PIPELINE_OUT, "aligned_answers.json")
with open(aligned_path, "w") as f:
    json.dump(aligned, f, indent=2, ensure_ascii=False)
shutil.copy2(aligned_path, os.path.join(DATASET_DIR, "aligned_answers_claude_ocr.json"))
print(f"✓ Aligned answers saved.")

# ── STAGE 5: Claude Grading ───────────────────────────────────────────────────
print("\n" + "="*60)
print("STAGE 5: Grading (Two-Phase — CLAUDE SONNET 4)")
print("="*60)

from claude_grading.answer_grader_claude import grade_all_answers

grading_results = grade_all_answers(aligned_answers=aligned, model_answers=aligned)

grading_path = os.path.join(GRADING_RES, "grading_final.json")
with open(grading_path, "w") as f:
    json.dump(grading_results, f, indent=2, ensure_ascii=False)
dest = os.path.join(DATASET_DIR, "grading_final_claude_ocr.json")
shutil.copy2(grading_path, dest)

meta = grading_results.get("metadata", {})
print(f"\n  Score: {meta.get('total_marks_obtained',0)}/{meta.get('total_marks_possible',0)}")
print(f"  Grade: {meta.get('grade','N/A')}")

# ── STAGE 6: PDF Report ───────────────────────────────────────────────────────
from generate_pdf_reports import generate_pdf
report_path = os.path.join(DATASET_DIR, "grading_report_claude_ocr.pdf")
generate_pdf(dest, report_path, "Grading Report — Paper 15155 (GST) — Claude AI + Claude OCR")
print(f"✓ Report saved: {report_path}")
