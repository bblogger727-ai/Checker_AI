#!/usr/bin/env python3
"""
CheckerAI JSON-Based Grading Pipeline — run_pipeline_json.py
=============================================================
Grades student answer sheets against pre-built paper JSONs.
No Question Paper PDF or Model Answer PDF required.

Supports two paper types via --paper-type:

  full  — Full mock paper (Section A MCQs + Section B descriptive sub-questions)
           • Builds schema_with_answers from the JSON (MCQs + Q1a/b/c, Q2a/b/c, …)
           • Section A: All MCQs graded (2 marks each)
           • Section B: All sub-questions graded individually (sub-part level)
           • Top-5 scoring rule: Q1 compulsory + best 4 of Q2–Q6 count toward total
           • Total marks: normalised to 100

  pt    — Portionwise Test (Section B only, 5 questions × 2 sub-parts each)
           • No MCQs; section_a is empty in the JSON
           • 5 main questions; each has exactly 2 sub-questions (a and b)
           • Both sub-questions graded and annotated separately
           • All 5 questions count; total marks = 50

Paper-code format:
  <SUBJECT>-<NUMBER>         →  Mock Paper        e.g.  AA-3  | LAW-2 | ACC-1
  <SUBJECT>-PT-<NUMBER>      →  Portionwise Test   e.g.  AA-PT-2 | TAX-PT-1

Usage:
  # Full mock paper
  python3 run_pipeline_json.py \\
      --paper-code AA-3 \\
      --paper-type full \\
      --as student_answer.pdf \\
      --dataset 15872

  # Portionwise test
  python3 run_pipeline_json.py \\
      --paper-code AA-PT-1 \\
      --paper-type pt \\
      --as student_answer.pdf \\
      --dataset 15879

  # See all valid paper codes
  python3 run_pipeline_json.py --list-codes
"""

import os
import sys
import json
import argparse
import time
import shutil
import traceback

# ── Path setup ────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# claude_grading module lives in CA_Feedback_Pipeline/
PIPELINE_DIR = os.path.join(os.path.dirname(BASE_DIR), "CA_Feedback_Pipeline")
sys.path.insert(0, PIPELINE_DIR)

from dotenv import load_dotenv
load_dotenv()

# Pipeline directories
PIPELINE_OUTPUT = os.path.join(BASE_DIR, "pipeline_output")
PIPELINE_TEMP   = os.path.join(BASE_DIR, "pipeline_temp")
GRADING_RESULTS = os.path.join(BASE_DIR, "grading_results")

# ── Import unchanged helpers from original pipeline ────────────────────────────
from run_pipeline import ensure_dirs, clear_temp, run_stage_6, run_stage_7
from generate_student_report import generate_student_report


# ══════════════════════════════════════════════════════════════════════════════
# PAPER CODE LOOKUP TABLE
# Maps short paper codes → absolute paths to the JSON files in All_Paper_JSONs.
# ══════════════════════════════════════════════════════════════════════════════

_JSON_ROOT = "/Users/gaureshmantri/Documents/Secure PDF Extraction/All_Paper_JSONs"

def _p(level: str, filename: str) -> str:
    """Shorthand to build an absolute JSON path."""
    return os.path.join(_JSON_ROOT, level, filename)


PAPER_CODE_MAP: dict[str, str] = {

    # ── FINAL ─────────────────────────────────────────────────────────────────

    # Advanced Auditing (AA)
    "AA-1":     _p("Final", "AA_Mock_Paper_1.json"),
    "AA-2":     _p("Final", "AA_Mock_Paper_2.json"),
    "AA-3":     _p("Final", "AA_Mock_Paper_3.json"),
    "AA-PT-1":  _p("Final", "AA_Portionwise_Test_1.json"),
    "AA-PT-2":  _p("Final", "AA_Portionwise_Test_2.json"),
    "AA-PT-3":  _p("Final", "AA_Portionwise_Test_3.json"),

    # Advanced Financial Management (AFM)
    "AFM-1":    _p("Final", "AFM_Mock_Paper_1.json"),
    "AFM-2":    _p("Final", "AFM_Mock_Paper_2.json"),
    "AFM-3":    _p("Final", "AFM_Mock_Paper_3.json"),
    "AFM-PT-1": _p("Final", "AFM_Portionwise_Test_1.json"),
    "AFM-PT-2": _p("Final", "AFM_Portionwise_Test_2.json"),
    "AFM-PT-3": _p("Final", "AFM_Portionwise_Test_3.json"),

    # Direct Tax (DT)
    "DT-1":     _p("Final", "DT_Mock_Paper_1.json"),
    "DT-2":     _p("Final", "DT_Mock_Paper_2.json"),
    "DT-3":     _p("Final", "DT_Mock_Paper_3.json"),
    "DT-PT-1":  _p("Final", "DT_Portionwise_Test_1.json"),
    "DT-PT-2":  _p("Final", "DT_Portionwise_Test_2.json"),
    "DT-PT-3":  _p("Final", "DT_Portionwise_Test_3.json"),

    # Financial Reporting (FR)
    "FR-1":     _p("Final", "FR_Mock_Paper_1.json"),
    "FR-2":     _p("Final", "FR_Mock_Paper_2.json"),
    "FR-3":     _p("Final", "FR_Mock_Paper_3.json"),
    "FR-PT-1":  _p("Final", "FR_Portionwise_Test_1.json"),
    "FR-PT-2":  _p("Final", "FR_Portionwise_Test_2.json"),
    "FR-PT-3":  _p("Final", "FR_Portionwise_Test_3.json"),

    # Indirect Tax (IDT)
    "IDT-1":    _p("Final", "IDT_Mock_Paper_1.json"),
    "IDT-2":    _p("Final", "IDT_Mock_Paper_2.json"),
    "IDT-3":    _p("Final", "IDT_Mock_Paper_3.json"),
    "IDT-PT-1": _p("Final", "IDT_Portionwise_Test_1.json"),
    "IDT-PT-2": _p("Final", "IDT_Portionwise_Test_2.json"),
    "IDT-PT-3": _p("Final", "IDT_Portionwise_Test_3.json"),

    # ── INTER ─────────────────────────────────────────────────────────────────

    # Advanced Accounts (ADVAC)
    "ADVAC-1":    _p("Inter", "ADVAC_Mock_Paper_1.json"),
    "ADVAC-2":    _p("Inter", "ADVAC_Mock_Paper_2.json"),
    "ADVAC-3":    _p("Inter", "ADVAC_Mock_Paper_3.json"),
    "ADVAC-PT-1": _p("Inter", "ADVAC_Portionwise_Test_1.json"),
    "ADVAC-PT-2": _p("Inter", "ADVAC_Portionwise_Test_2.json"),
    "ADVAC-PT-3": _p("Inter", "ADVAC_Portionwise_Test_3.json"),

    # Auditing (AUD)
    "AUD-1":    _p("Inter", "AUD_Mock_Paper_1.json"),
    "AUD-2":    _p("Inter", "AUD_Mock_Paper_2.json"),
    "AUD-3":    _p("Inter", "AUD_Mock_Paper_3.json"),
    "AUD-PT-1": _p("Inter", "AUD_Portionwise_Test_1.json"),
    "AUD-PT-2": _p("Inter", "AUD_Portionwise_Test_2.json"),
    "AUD-PT-3": _p("Inter", "AUD_Portionwise_Test_3.json"),

    # Cost Accounting (COST)
    "COST-1":    _p("Inter", "COST_Mock_Paper_1.json"),
    "COST-2":    _p("Inter", "COST_Mock_Paper_2.json"),
    "COST-3":    _p("Inter", "COST_Mock_Paper_3.json"),
    "COST-PT-1": _p("Inter", "COST_Portionwise_Test_1.json"),
    "COST-PT-2": _p("Inter", "COST_Portionwise_Test_2.json"),
    "COST-PT-3": _p("Inter", "COST_Portionwise_Test_3.json"),

    # Financial Management (FM)
    "FM-1":    _p("Inter", "FM_Mock_Paper_1.json"),
    "FM-2":    _p("Inter", "FM_Mock_Paper_2.json"),
    "FM-3":    _p("Inter", "FM_Mock_Paper_3.json"),
    "FM-PT-1": _p("Inter", "FM_Portionwise_Test_1.json"),
    "FM-PT-2": _p("Inter", "FM_Portionwise_Test_2.json"),
    "FM-PT-3": _p("Inter", "FM_Portionwise_Test_3.json"),

    # Law (LAW)
    "LAW-1":    _p("Inter", "LAW_Mock_Paper_1.json"),
    "LAW-2":    _p("Inter", "LAW_Mock_Paper_2.json"),
    "LAW-3":    _p("Inter", "LAW_Mock_Paper_3.json"),
    "LAW-PT-1": _p("Inter", "LAW_Portionwise_Test_1.json"),
    "LAW-PT-2": _p("Inter", "LAW_Portionwise_Test_2.json"),
    "LAW-PT-3": _p("Inter", "LAW_Portionwise_Test_3.json"),

    # Taxation (TAX)
    "TAX-1":    _p("Inter", "TAX_Mock_Paper_1.json"),
    "TAX-2":    _p("Inter", "TAX_Mock_Paper_2.json"),
    "TAX-3":    _p("Inter", "TAX_Mock_Paper_3.json"),
    "TAX-PT-1": _p("Inter", "TAX_Portionwise_Test_1.json"),
    "TAX-PT-2": _p("Inter", "TAX_Portionwise_Test_2.json"),
    "TAX-PT-3": _p("Inter", "TAX_Portionwise_Test_3.json"),

    # ── FOUNDATION ────────────────────────────────────────────────────────────

    # Accounting (ACC)
    "ACC-1":    _p("Foundation", "Accounting_Mock_Paper_1.json"),
    "ACC-2":    _p("Foundation", "Accounting_Mock_Paper_2.json"),
    "ACC-3":    _p("Foundation", "Accounting_Mock_Paper_3.json"),
    "ACC-PT-1": _p("Foundation", "Accounting_Portionwise_Test_1.json"),
    "ACC-PT-2": _p("Foundation", "Accounting_Portionwise_Test_2.json"),

    # Business Economics (BE)
    "BE-1": _p("Foundation", "Business_Economics_Mock_Paper_1.json"),
    "BE-2": _p("Foundation", "Business_Economics_Mock_Paper_2.json"),
    "BE-3": _p("Foundation", "Business_Economics_Mock_Paper_3.json"),

    # Business Laws (BL)
    "BL-1":    _p("Foundation", "Business_Laws_Mock_Paper_1.json"),
    "BL-2":    _p("Foundation", "Business_Laws_Mock_Paper_2.json"),
    "BL-3":    _p("Foundation", "Business_Laws_Mock_Paper_3.json"),
    "BL-PT-1": _p("Foundation", "Business_Laws_Portionwise_Test_1.json"),
    "BL-PT-2": _p("Foundation", "Business_Laws_Portionwise_Test_2.json"),
}


def resolve_paper_json(paper_code: str) -> str:
    """
    Resolve a short paper code to the absolute path of its JSON file.
    Case-insensitive. Raises ValueError with a helpful message on failure.
    """
    normalised = paper_code.strip().upper()
    path = PAPER_CODE_MAP.get(normalised)
    if path is None:
        available = "\n  ".join(sorted(PAPER_CODE_MAP.keys()))
        raise ValueError(
            f"Unknown paper code: '{paper_code}'\n"
            f"Available codes:\n  {available}"
        )
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Paper code '{paper_code}' resolved to:\n  {path}\n"
            f"But that file does not exist. Check that the JSONs folder is intact."
        )
    return path


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 1+2 — FULL MOCK PAPER
# Builds schema_with_answers from a full mock paper JSON.
# Produces: SectionA.MCQ + SectionB with Q1a/Q1b/Q1c etc. as individual keys.
# ══════════════════════════════════════════════════════════════════════════════

def run_stage_1_2_full(paper_json_path: str) -> dict:
    """
    Build schema_with_answers from a full mock paper JSON.

    Output structure:
    {
      "SectionA": {
        "MCQ": {
          "1": { "question": "...", "model_answer": "c", "marks": 2, "question_number": "Q1" },
          ...
        }
      },
      "SectionB": {
        "Q1": {
          "Q1a": { "question": "...", "model_answer": "...", "marks": 5, "question_number": "Q1a" },
          "Q1b": { ... },
          "Q1c": { ... }
        },
        "Q2": { ... },
        ...
      }
    }

    Top-5 scoring (Q1 compulsory + best 4 of Q2–Q6) is applied in Stage 5.
    """
    print("\n" + "=" * 60)
    print("STAGE 1+2 (FULL): Building schema_with_answers from mock paper JSON")
    print("=" * 60)
    print(f"Paper JSON: {paper_json_path}")

    with open(paper_json_path, "r", encoding="utf-8") as f:
        paper = json.load(f)

    meta = paper.get("meta", {})
    print(f"  Subject : {meta.get('subject_name', 'N/A')} ({meta.get('subject_code', 'N/A')})")
    print(f"  Paper # : {meta.get('paper_num', 'N/A')}")

    schema_with_answers: dict = {}

    # ── Section A: MCQs ──────────────────────────────────────────────────────
    section_a_raw = paper.get("section_a", [])
    mcq_block: dict = {}
    serial_counter = 0

    for case_study in section_a_raw:
        for q in case_study.get("questions", []):
            serial = q.get("_serial") or q.get("q_num")
            if serial is None:
                serial_counter += 1
                serial = serial_counter
            else:
                serial_counter = int(serial)

            key = str(serial)
            correct = q.get("correct_option", q.get("answer", ""))
            correct = correct.strip("() ").lower()
            if correct:
                correct = correct[0]

            mcq_block[key] = {
                "question":        q.get("question", ""),
                "options":         q.get("options", {}),
                "model_answer":    correct,
                "marks":           2,
                "question_number": f"Q{serial}",
            }

    schema_with_answers["SectionA"] = {"MCQ": mcq_block}
    print(f"  Section A: {len(mcq_block)} MCQs built")

    # ── Section B: Descriptive sub-part questions ─────────────────────────────
    section_b_raw = paper.get("section_b", [])
    section_b_block: dict = {}

    for main_q in section_b_raw:
        q_main  = main_q.get("q_main")
        q_key   = f"Q{q_main}"
        sub_q_block: dict = {}

        for sub in main_q.get("sub_questions", []):
            label   = sub.get("label", "")
            sub_key = f"Q{q_main}{label}"
            marks   = sub.get("marks", 5)

            sub_q_block[sub_key] = {
                "question":        sub.get("question", ""),
                "model_answer":    sub.get("answer", ""),
                "marks":           marks,
                "question_number": sub_key,
                "chapter_number":  sub.get("chapter_number", ""),
                "chapter_name":    sub.get("chapter_name", ""),
            }

        section_b_block[q_key] = sub_q_block

    schema_with_answers["SectionB"] = section_b_block

    total_sub_qs = sum(len(v) for v in section_b_block.values())
    print(f"  Section B: {len(section_b_block)} main questions, {total_sub_qs} sub-parts built")

    _persist_schema(schema_with_answers, paper_json_path, meta)
    return schema_with_answers


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 1+2 — PORTIONWISE TEST (PT)
# Builds schema_with_answers from a portionwise test JSON.
# 5 main questions, each with exactly 2 sub-questions (a and b).
# No MCQs. Total = 50 marks. All questions count.
# ══════════════════════════════════════════════════════════════════════════════

def run_stage_1_2_pt(paper_json_path: str) -> dict:
    """
    Build schema_with_answers from a portionwise test JSON.

    Output structure (no SectionA, all questions under SectionB):
    {
      "SectionA": { "MCQ": {} },    <-- empty, kept for pipeline compatibility
      "SectionB": {
        "Q1": {
          "Q1a": { "question": "...", "model_answer": "...", "marks": 6, "question_number": "Q1a" },
          "Q1b": { "question": "...", "model_answer": "...", "marks": 4, "question_number": "Q1b" }
        },
        "Q2": { ... },
        "Q3": { ... },
        "Q4": { ... },
        "Q5": { ... }
      }
    }

    All 5 questions count toward total (no top-N rule for PT).
    """
    print("\n" + "=" * 60)
    print("STAGE 1+2 (PT): Building schema_with_answers from portionwise test JSON")
    print("=" * 60)
    print(f"Paper JSON: {paper_json_path}")

    with open(paper_json_path, "r", encoding="utf-8") as f:
        paper = json.load(f)

    meta = paper.get("meta", {})
    print(f"  Subject      : {meta.get('subject_name', 'N/A')} ({meta.get('subject_code', 'N/A')})")
    print(f"  Paper #      : {meta.get('paper_num', 'N/A')}")
    print(f"  Total marks  : {meta.get('total_marks_printed', 50)}")
    print(f"  Note         : {meta.get('note', '')}")

    schema_with_answers: dict = {}

    # Section A is empty for PT; include stub for pipeline compatibility
    schema_with_answers["SectionA"] = {"MCQ": {}}

    # ── Section B: 5 main questions × 2 sub-questions each ───────────────────
    section_b_raw = paper.get("section_b", [])
    section_b_block: dict = {}

    if len(section_b_raw) != 5:
        print(f"  ⚠ Warning: expected 5 main questions in PT, found {len(section_b_raw)}")

    for main_q in section_b_raw:
        q_main     = main_q.get("q_main")
        q_key      = f"Q{q_main}"
        sub_qs     = main_q.get("sub_questions", [])
        sub_q_block: dict = {}

        if len(sub_qs) != 2:
            print(f"  ⚠ Warning: Q{q_main} has {len(sub_qs)} sub-questions (expected 2)")

        for sub in sub_qs:
            label   = sub.get("label", "")       # "a" or "b"
            sub_key = f"Q{q_main}{label}"         # "Q1a", "Q1b", …
            marks   = sub.get("marks", 5)

            sub_q_block[sub_key] = {
                "question":        sub.get("question", ""),
                "model_answer":    sub.get("answer", ""),
                "marks":           marks,
                "question_number": sub_key,
                "chapter_number":  sub.get("chapter_number", ""),
                "chapter_name":    sub.get("chapter_name", ""),
            }

        section_b_block[q_key] = sub_q_block

    schema_with_answers["SectionB"] = section_b_block

    total_marks = sum(
        sub_val.get("marks", 0)
        for q_val in section_b_block.values()
        for sub_val in q_val.values()
    )
    print(f"  Section B: {len(section_b_block)} questions × 2 sub-parts built (total: {total_marks} marks)")

    _persist_schema(schema_with_answers, paper_json_path, meta)
    return schema_with_answers


def _persist_schema(schema_with_answers: dict, paper_json_path: str, meta: dict) -> None:
    """Save schema_with_answers.json and schema.json to pipeline_output/."""
    os.makedirs(PIPELINE_OUTPUT, exist_ok=True)

    swa_path = os.path.join(PIPELINE_OUTPUT, "schema_with_answers.json")
    with open(swa_path, "w", encoding="utf-8") as f:
        json.dump(schema_with_answers, f, indent=2, ensure_ascii=False)
    print(f"✓ schema_with_answers saved to: {swa_path}")

    schema_meta = {"paper_json": paper_json_path, "meta": meta}
    schema_path = os.path.join(PIPELINE_OUTPUT, "schema.json")
    with open(schema_path, "w", encoding="utf-8") as f:
        json.dump(schema_meta, f, indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 5 — TOP-5 SCORING (full paper only)
# ══════════════════════════════════════════════════════════════════════════════

def _calculate_grade(percentage: float) -> str:
    if percentage >= 60: return "A"
    elif percentage >= 50: return "B"
    elif percentage >= 40: return "C"
    elif percentage >= 33: return "D"
    else: return "F"


def _apply_top5_scoring(grading_results: dict, compulsory_q: str = "Q1") -> dict:
    """
    Post-process grading_results for full papers:
      - Q1 (compulsory) always counts.
      - From Q2–Q6, pick the 4 with the highest marks_obtained.
      - Re-compute total and percentage using only those 5 questions.
      - total_marks_possible = 100.
      - Excluded questions are still annotated but flagged excluded_from_total=True.
    """
    graded     = grading_results.get("graded_answers", {})
    section_b  = graded.get("SectionB", {})

    def q_total_obtained(q_content: dict) -> float:
        return sum(
            float(v.get("marks_obtained", 0))
            for v in q_content.values()
            if isinstance(v, dict) and "marks_obtained" in v
        )

    # Separate compulsory and optional
    optional_scores: list[tuple[str, float]] = [
        (q_key, q_total_obtained(q_content))
        for q_key, q_content in section_b.items()
        if q_key != compulsory_q
    ]

    optional_scores.sort(key=lambda x: x[1], reverse=True)
    top4_keys      = {k for k, _ in optional_scores[:4]}
    excluded_keys  = {k for k, _ in optional_scores[4:]}

    for q_key in excluded_keys:
        for sub_val in section_b.get(q_key, {}).values():
            if isinstance(sub_val, dict):
                sub_val["excluded_from_total"] = True
                sub_val["exclusion_reason"] = (
                    f"{q_key} not counted: lower-scoring optional excluded under top-4 rule"
                )

    # Recalculate totals
    total_obtained = 0.0
    for mcq_val in graded.get("SectionA", {}).get("MCQ", {}).values():
        if isinstance(mcq_val, dict):
            total_obtained += float(mcq_val.get("marks_obtained", 0))

    counted_keys = {compulsory_q} | top4_keys
    for q_key in counted_keys:
        total_obtained += q_total_obtained(section_b.get(q_key, {}))

    percentage = round((total_obtained / 100.0) * 100, 2)

    grading_results["metadata"]["total_marks_possible"]  = 100
    grading_results["metadata"]["total_marks_obtained"]  = round(total_obtained, 2)
    grading_results["metadata"]["percentage"]            = percentage
    grading_results["metadata"]["grade"]                 = _calculate_grade(percentage)
    grading_results["metadata"]["scoring_rule"] = (
        f"Full paper: Q1 compulsory + top 4 of Q2-Q6 by marks obtained. "
        f"Excluded: {sorted(excluded_keys) or 'none'}. Total /100."
    )
    grading_results["metadata"]["top5_questions"]        = sorted(counted_keys)
    grading_results["metadata"]["excluded_questions"]    = sorted(excluded_keys)

    print(f"\n  Top-5 scoring applied:")
    print(f"    Counted questions : {sorted(counted_keys)}")
    if excluded_keys:
        print(f"    Excluded questions: {sorted(excluded_keys)}")
    print(f"    Total obtained    : {total_obtained:.1f} / 100")
    print(f"    Percentage        : {percentage}%")
    return grading_results


def _apply_pt_scoring(grading_results: dict, total_marks_possible: float) -> dict:
    """
    Post-process grading_results for portionwise tests:
      - All 5 questions count.
      - total_marks_possible is passed in from schema_with_answers (graded_answers
        does NOT preserve the 'marks' field, only 'marks_obtained').
      - Percentage = obtained / total_marks_possible * 100.
    """
    graded    = grading_results.get("graded_answers", {})
    section_b = graded.get("SectionB", {})

    total_obtained = 0.0
    for q_content in section_b.values():
        for sub_val in q_content.values():
            if isinstance(sub_val, dict) and "marks_obtained" in sub_val:
                total_obtained += float(sub_val.get("marks_obtained", 0))

    percentage = round(
        (total_obtained / total_marks_possible * 100) if total_marks_possible else 0, 2
    )

    grading_results["metadata"]["total_marks_possible"] = round(total_marks_possible, 2)
    grading_results["metadata"]["total_marks_obtained"] = round(total_obtained, 2)
    grading_results["metadata"]["percentage"]           = percentage
    grading_results["metadata"]["grade"]                = _calculate_grade(percentage)
    grading_results["metadata"]["scoring_rule"] = (
        f"Portionwise test: All 5 questions graded individually (a & b separately). "
        f"Total /{round(total_marks_possible)}."
    )

    print(f"\n  PT scoring applied:")
    print(f"    Total obtained : {total_obtained:.1f} / {total_marks_possible:.0f}")
    print(f"    Percentage     : {percentage}%")
    return grading_results


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 3: OCR (CLAUDE — unchanged from run_pipeline_claude.py)
# ══════════════════════════════════════════════════════════════════════════════

def run_stage_3_claude(as_pdf: str) -> str:
    print("\n" + "=" * 60)
    print("STAGE 3: OCR Extraction (CLAUDE VISION)")
    print("=" * 60)

    from claude_grading.ocr_service_claude import ocr_pdf_claude

    print(f"Extracting handwritten text from: {as_pdf}")
    print("Using Claude Sonnet 4 Vision (this may take a few minutes)...")

    ocr_path = os.path.join(PIPELINE_TEMP, "3_ocr_output.txt")
    ocr_text = ocr_pdf_claude(as_pdf, output_path=ocr_path)

    print(f"✓ OCR completed. Saved to: {ocr_path}")
    return ocr_text


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 4: Alignment (CLAUDE — unchanged from run_pipeline_claude.py)
# ══════════════════════════════════════════════════════════════════════════════

def run_stage_4_claude(schema_with_answers: dict, ocr_text: str) -> dict:
    print("\n" + "=" * 60)
    print("STAGE 4: Answer Alignment (CLAUDE SONNET 4)")
    print("=" * 60)

    from claude_grading.answer_aligner_claude import align_answers_to_schema_claude

    print("Parsing OCR text...")
    pages = []
    for block in ocr_text.split("=== Page "):
        if not block.strip():
            continue
        try:
            header, content = block.split("===", 1)
            pages.append({"page": int(header.strip()), "text": content.strip()})
        except Exception:
            pass

    print(f"Parsed {len(pages)} pages")
    print("Aligning student answers to schema (Claude Sonnet 4)...")

    aligned = align_answers_to_schema_claude(pages, schema_with_answers)

    aligned_path = os.path.join(PIPELINE_OUTPUT, "aligned_answers.json")
    with open(aligned_path, "w") as f:
        json.dump(aligned, f, indent=2, ensure_ascii=False)
    print(f"✓ Aligned answers saved to: {aligned_path}")

    return aligned


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 5: Grading (CLAUDE — unchanged logic, scoring rule varies by paper-type)
# ══════════════════════════════════════════════════════════════════════════════

def run_stage_5_claude(aligned: dict, paper_type: str, schema_with_answers: dict | None = None) -> dict:
    print("\n" + "=" * 60)
    print(f"STAGE 5: Grading (CLAUDE SONNET 4) — paper-type: {paper_type}")
    print("=" * 60)

    from claude_grading.answer_grader_claude import grade_all_answers

    print("Grading sub-part answers with Claude Sonnet 4...")
    grading_results = grade_all_answers(
        aligned_answers=aligned,
        model_answers=aligned
    )

    # Apply the correct scoring rule
    if paper_type == "full":
        grading_results = _apply_top5_scoring(grading_results, compulsory_q="Q1")
    else:  # pt
        # Compute total_marks_possible from schema_with_answers.
        # We CANNOT read it from graded_answers because the grader output
        # does not preserve the 'marks' field — only 'marks_obtained'.
        total_possible = 0.0
        if schema_with_answers:
            for q_val in schema_with_answers.get("SectionB", {}).values():
                for sub_val in q_val.values():
                    if isinstance(sub_val, dict):
                        total_possible += float(sub_val.get("marks", 0))
        if total_possible == 0.0:
            # Fallback: standard PT is 50 marks
            total_possible = 50.0
            print("  ⚠ Could not compute total marks from schema — defaulting to 50")
        grading_results = _apply_pt_scoring(grading_results, total_marks_possible=total_possible)

    os.makedirs(GRADING_RESULTS, exist_ok=True)
    grading_path = os.path.join(GRADING_RESULTS, "grading_final.json")
    with open(grading_path, "w") as f:
        json.dump(grading_results, f, indent=2, ensure_ascii=False)

    print(f"✓ Grading results saved to: {grading_path}")
    if "metadata" in grading_results:
        m = grading_results["metadata"]
        print(f"  Score     : {m.get('total_marks_obtained', 0)}/{m.get('total_marks_possible', 0)}")
        print(f"  Percentage: {m.get('percentage', 0):.2f}%")
        print(f"  Grade     : {m.get('grade', 'N/A')}")

    return grading_results


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description=(
            "CheckerAI JSON-Based Grading Pipeline\n"
            "Grades a student answer sheet against a pre-built paper JSON.\n"
            "No QP or model answer PDF needed.\n\n"
            "Examples:\n"
            "  # Full mock paper\n"
            "  python3 run_pipeline_json.py --paper-code AA-3 --paper-type full --as student.pdf --dataset 15872\n\n"
            "  # Portionwise test\n"
            "  python3 run_pipeline_json.py --paper-code AA-PT-1 --paper-type pt --as student.pdf --dataset 15879\n\n"
            "  # See all valid codes\n"
            "  python3 run_pipeline_json.py --list-codes"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--paper-code", default=None,
        help="Short paper code, e.g. AA-3, AA-PT-1, LAW-2, TAX-PT-3. Use --list-codes to see all."
    )
    parser.add_argument(
        "--paper-type", choices=["full", "pt"], default=None,
        help=(
            '"full" = Full mock paper (MCQs + Section B, top-5 scoring, total /100). '
            '"pt"   = Portionwise test (5 Qs × 2 sub-parts, all count, total /50).'
        )
    )
    parser.add_argument(
        "--as", dest="as_pdf", default=None,
        help="Path to the Student Answer Sheet PDF"
    )
    parser.add_argument(
        "--dataset", default=None,
        help="Dataset ID for organising results (defaults to digits from --as filename)"
    )
    parser.add_argument(
        "--skip-to", type=int, default=1,
        help=(
            "Skip to stage N:\n"
            "  1 = full run (default)\n"
            "  4 = skip schema build + OCR (load from disk)\n"
            "  5 = skip alignment (load aligned_answers.json from disk)\n"
            "  6 = skip all grading, just re-run report + checked copy"
        )
    )
    parser.add_argument(
        "--skip-ocr", action="store_true",
        help="Skip OCR (Stage 3) and use cached ocr_output.txt if available"
    )
    parser.add_argument(
        "--list-codes", action="store_true",
        help="Print all valid paper codes and exit"
    )

    args = parser.parse_args()

    # ── --list-codes ──────────────────────────────────────────────────────────
    if args.list_codes:
        print("Valid paper codes:\n")
        prev_prefix = ""
        for code in sorted(PAPER_CODE_MAP.keys()):
            subject = code.split("-")[0]
            if subject != prev_prefix:
                print()
                prev_prefix = subject
            print(f"  {code:20s}  →  {PAPER_CODE_MAP[code]}")
        print()
        sys.exit(0)

    # ── Validate required args ────────────────────────────────────────────────
    if not args.paper_code:
        parser.error("--paper-code is required (or use --list-codes to see all valid codes)")
    if not args.paper_type:
        parser.error('--paper-type is required: "full" for mock papers, "pt" for portionwise tests')
    if not args.as_pdf:
        parser.error("--as (student answer sheet PDF) is required")

    # ── Resolve paper code → JSON path ────────────────────────────────────────
    try:
        paper_json_path = resolve_paper_json(args.paper_code)
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}")
        sys.exit(1)

    # ── Setup dataset dir ──────────────────────────────────────────────────────
    dataset_id = args.dataset
    if not dataset_id:
        basename   = os.path.splitext(os.path.basename(args.as_pdf))[0]
        dataset_id = "".join(c for c in basename if c.isdigit()) or "default"

    dataset_dir = os.path.join(GRADING_RESULTS, f"dataset_{dataset_id}")
    os.makedirs(dataset_dir, exist_ok=True)

    paper_type_label = "Full Mock Paper" if args.paper_type == "full" else "Portionwise Test"

    print("=" * 60)
    print(f"  CHECKERAI JSON-BASED GRADING PIPELINE (Claude Sonnet 4)")
    print(f"  Paper Code : {args.paper_code.upper()}  [{paper_type_label}]")
    print(f"  Paper JSON : {paper_json_path}")
    print(f"  Student AS : {args.as_pdf}")
    print(f"  Dataset    : {dataset_id}")
    print(f"  Dataset dir: {dataset_dir}")
    print("=" * 60)

    start_time = time.time()
    ensure_dirs()

    if args.skip_to <= 1:
        clear_temp()

    try:
        # ── STAGE 1+2 (JSON): Build schema ────────────────────────────────────
        if args.skip_to <= 2:
            if args.paper_type == "full":
                schema_with_answers = run_stage_1_2_full(paper_json_path)
            else:
                schema_with_answers = run_stage_1_2_pt(paper_json_path)
        else:
            swa_path = os.path.join(PIPELINE_OUTPUT, "schema_with_answers.json")
            with open(swa_path, "r") as f:
                schema_with_answers = json.load(f)
            print(f"[SKIP] Stages 1+2 — loaded schema_with_answers from {swa_path}")

        # ── STAGE 3 (CLAUDE): OCR ─────────────────────────────────────────────
        ocr_dataset_path          = os.path.join(dataset_dir, "ocr_output_claude.txt")
        ocr_dataset_path_fallback = os.path.join(dataset_dir, "ocr_output.txt")

        if args.skip_to <= 3 and not args.skip_ocr:
            ocr_text = run_stage_3_claude(args.as_pdf)
        else:
            if os.path.exists(ocr_dataset_path):
                with open(ocr_dataset_path, "r") as f:
                    ocr_text = f.read()
                print(f"[SKIP] Stage 3 — loaded OCR from {ocr_dataset_path}")
            elif os.path.exists(ocr_dataset_path_fallback):
                with open(ocr_dataset_path_fallback, "r") as f:
                    ocr_text = f.read()
                print(f"[SKIP] Stage 3 — loaded OCR from {ocr_dataset_path_fallback}")
            else:
                ocr_path = os.path.join(PIPELINE_TEMP, "3_ocr_output.txt")
                with open(ocr_path, "r") as f:
                    ocr_text = f.read()
                print(f"[SKIP] Stage 3 — loaded OCR from {ocr_path}")

        # ── STAGE 4 (CLAUDE): Alignment ───────────────────────────────────────
        if args.skip_to <= 4:
            aligned = run_stage_4_claude(schema_with_answers, ocr_text)
        else:
            aligned_path = os.path.join(PIPELINE_OUTPUT, "aligned_answers.json")
            with open(aligned_path, "r") as f:
                aligned = json.load(f)
            print(f"[SKIP] Stage 4 — loaded aligned from {aligned_path}")

        # ── STAGE 5 (CLAUDE): Grading ─────────────────────────────────────────
        if args.skip_to <= 5:
            grading_results = run_stage_5_claude(aligned, paper_type=args.paper_type, schema_with_answers=schema_with_answers)
        else:
            grading_path = os.path.join(GRADING_RESULTS, "grading_final.json")
            print(f"[SKIP] Stage 5 — using existing {grading_path}")

        # ── Copy all results to dataset dir ───────────────────────────────────
        print(f"\nCopying results to {dataset_dir}...")
        for fname in ["schema.json", "schema_with_answers.json", "aligned_answers.json"]:
            src = os.path.join(PIPELINE_OUTPUT, fname)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(dataset_dir, fname))
        src_ocr  = os.path.join(PIPELINE_TEMP, "3_ocr_output.txt")
        dest_ocr = os.path.join(dataset_dir, "ocr_output.txt")
        if os.path.exists(src_ocr) and not os.path.exists(dest_ocr):
            shutil.copy2(src_ocr, dest_ocr)
        grading_src = os.path.join(GRADING_RESULTS, "grading_final.json")
        if os.path.exists(grading_src) and args.skip_to <= 5:
            shutil.copy2(grading_src, os.path.join(dataset_dir, "grading_final.json"))

        # ── STAGE 6: PDF grading report ───────────────────────────────────────
        run_stage_6(dataset_dir)

        # ── STAGE 7: Annotated checked copy ───────────────────────────────────
        run_stage_7(as_path=args.as_pdf, dataset_dir=dataset_dir)

        # ── STAGE 8: Student performance report ───────────────────────────────
        grading_json_for_report = os.path.join(dataset_dir, "grading_final.json")
        if not os.path.exists(grading_json_for_report):
            grading_json_for_report = os.path.join(GRADING_RESULTS, "grading_final.json")
        generate_student_report(
            grading_json_path=grading_json_for_report,
            dataset_dir=dataset_dir,
            dataset_id=args.dataset,
        )

        elapsed = time.time() - start_time
        print("\n" + "=" * 60)
        print(f"  ✓ PIPELINE COMPLETE in {elapsed:.1f}s")
        print(f"  Paper     : {args.paper_code.upper()}  [{paper_type_label}]")
        print(f"  Graded by : Claude Sonnet 4")
        print(f"  Results   : {dataset_dir}/")
        print(f"    schema_with_answers.json — built from paper JSON (no QP/SA PDFs)")
        print(f"    ocr_output.txt           — Claude OCR of student answer sheet")
        print(f"    aligned_answers.json     — answers aligned to schema")
        print(f"    grading_final.json       — grading results")
        print(f"    grading_report.pdf       — teacher grading report")
        print(f"    checked_copy.pdf         — annotated student answer sheet")
        print(f"    student_report.txt       — student performance report")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ PIPELINE FAILED: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
