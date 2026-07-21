#!/usr/bin/env python3
"""
FT Pipeline Runner — Full-Test (FT) Paper Grading
===================================================
Designed for papers where the question paper + model answers already exist
as a single structured JSON (e.g. AA_Mock_Paper_3.json).

Key differences from run_pipeline.py / run_pipeline_claude.py:
  - Stages 1 & 2 are REPLACED by run_stage_1_2_FT() which maps the paper JSON
    into the internal schema_with_answers format used by Stage 4 (alignment).
  - Stage 3 (OCR) is SKIPPED — OCR output is loaded directly from the existing
    dataset folder (ocr_output.txt).
  - Grading (Stage 5) happens at the **sub-part level**:
      Q1 with sub_questions [a, b, c] → graded as Q1a, Q1b, Q1c separately.
  - Section B "attempt any N of M" rule is handled:
      * All answered questions are graded and annotated.
      * For scoring totals, only the top-5 question marks count (Q1 compulsory +
        whichever 4 optional scored highest). Total is normalised to 100.

Usage:
  python3 run_pipeline_FT.py \\
      --FT  ../../AA_Mock_Paper_3.json \\
      --as  "AS FR 15872.pdf" \\
      --dataset 15872 \\
      [--skip-to 4]          # skip to stage 4 (alignment) if schema already built
      [--skip-to 5]          # skip to stage 5 (grading) if aligned_answers ready
      [--skip-to 6]          # skip all grading, just re-run report + checked copy

Note: --qp and --sa are NOT used in FT mode.
"""

import os
import sys
import json
import argparse
import time
import shutil
import traceback

# Setup paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# claude_grading module
PIPELINE_DIR = os.path.join(os.path.dirname(BASE_DIR), "CA_Feedback_Pipeline")
sys.path.insert(0, PIPELINE_DIR)

from dotenv import load_dotenv
load_dotenv()

# Pipeline directories (same as original)
PIPELINE_OUTPUT = os.path.join(BASE_DIR, "pipeline_output")
PIPELINE_TEMP   = os.path.join(BASE_DIR, "pipeline_temp")
GRADING_RESULTS = os.path.join(BASE_DIR, "grading_results")

# Re-use unchanged helpers from the original pipeline
from run_pipeline import ensure_dirs, clear_temp, run_stage_6, run_stage_7
from generate_student_report import generate_student_report


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 1+2 FT: Build schema_with_answers from the FT paper JSON
# ══════════════════════════════════════════════════════════════════════════════

def run_stage_1_2_FT(ft_paper_json_path: str) -> dict:
    """
    Read an FT paper JSON (e.g. AA_Mock_Paper_3.json) and produce the
    internal schema_with_answers dict expected by Stage 4 (alignment).

    Output structure mirrors what run_stage_2 / run_stage_2_claude produce:

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

    Each sub-question becomes its own top-level grading key so the recursive
    grader in answer_grader.py handles them individually.
    """
    print("\n" + "=" * 60)
    print("STAGE 1+2 FT: Building schema from FT paper JSON")
    print("=" * 60)
    print(f"FT paper JSON: {ft_paper_json_path}")

    with open(ft_paper_json_path, "r", encoding="utf-8") as f:
        paper = json.load(f)

    # Allow bypassing if the input is already a schema_with_answers.json
    if "SectionA" in paper or "SectionB" in paper:
        print("    [!] Input JSON is already a schema_with_answers format. Bypassing conversion.")
        
        # Save a copy to PIPELINE_OUTPUT to fulfill stage contract
        swa_path = os.path.join(PIPELINE_OUTPUT, "schema_with_answers.json")
        with open(swa_path, "w", encoding="utf-8") as f:
            json.dump(paper, f, indent=2, ensure_ascii=False)
        return paper

    schema_with_answers: dict = {
        "paper_meta": paper.get("meta", {})
    }

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
            # Normalise: strip parentheses, lowercase, take first char
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

    # ── Section B: Descriptive / Sub-part questions ───────────────────────────
    section_b_raw = paper.get("section_b", [])
    section_b_block: dict = {}

    for main_q in section_b_raw:
        q_main = main_q.get("q_main")
        q_key  = f"Q{q_main}"
        sub_q_block: dict = {}

        for sub in main_q.get("sub_questions", []):
            label    = sub.get("label", "")          # "a", "b", "c"
            sub_key  = f"Q{q_main}{label}"           # "Q1a", "Q1b", ...
            marks    = sub.get("marks", 5)
            question = sub.get("question", "")
            answer   = sub.get("answer", "")

            sub_q_block[sub_key] = {
                "question":        question,
                "model_answer":    answer,
                "marks":           marks,
                "question_number": sub_key,
                "chapter_number":  sub.get("chapter_number", ""),
                "chapter_name":    sub.get("chapter_name", ""),
            }

        section_b_block[q_key] = sub_q_block

    schema_with_answers["SectionB"] = section_b_block

    # Persist to pipeline_output/ so later stages can reload it
    os.makedirs(PIPELINE_OUTPUT, exist_ok=True)
    swa_path = os.path.join(PIPELINE_OUTPUT, "schema_with_answers.json")
    with open(swa_path, "w", encoding="utf-8") as f:
        json.dump(schema_with_answers, f, indent=2, ensure_ascii=False)
    print(f"✓ schema_with_answers (FT) saved to: {swa_path}")

    # Also save a minimal schema.json for compatibility
    schema_meta = {
        "paper_json": ft_paper_json_path,
        "meta":       paper.get("meta", {}),
    }
    schema_path = os.path.join(PIPELINE_OUTPUT, "schema.json")
    with open(schema_path, "w", encoding="utf-8") as f:
        json.dump(schema_meta, f, indent=2, ensure_ascii=False)

    return schema_with_answers


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 3 FT: Load existing OCR from dataset folder (no re-OCR)
# ══════════════════════════════════════════════════════════════════════════════

def run_stage_3_FT(dataset_dir: str, as_pdf: str) -> str:
    """
    Load pre-existing OCR output from the dataset folder.
    Tries ocr_output.txt (standard) and ocr_output_claude.txt (Claude variant).
    If not found, it runs Claude Vision OCR on the as_pdf to generate it.
    Copies it into pipeline_temp/ so Stage 4 can find it at the expected path.
    """
    print("\n" + "=" * 60)
    print("STAGE 3 FT: Loading or Extracting OCR")
    print("=" * 60)

    candidates = [
        os.path.join(dataset_dir, "ocr_output.txt"),
        os.path.join(dataset_dir, "ocr_output_claude.txt"),
    ]

    for path in candidates:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                ocr_text = f.read()
            # Mirror to pipeline_temp for Stage 4 compatibility
            dest = os.path.join(PIPELINE_TEMP, "3_ocr_output.txt")
            if path != dest:
                shutil.copy2(path, dest)
            print(f"✓ Loaded OCR from: {path}  ({len(ocr_text):,} chars)")
            return ocr_text

    print(f"No existing OCR found in {dataset_dir}. Running Claude Vision OCR extraction...")
    from claude_grading.ocr_service_claude import ocr_pdf_claude
    
    ocr_path = os.path.join(dataset_dir, "ocr_output.txt")
    ocr_text = ocr_pdf_claude(as_pdf, output_path=ocr_path)
    
    dest = os.path.join(PIPELINE_TEMP, "3_ocr_output.txt")
    shutil.copy2(ocr_path, dest)
    print(f"✓ OCR completed. Saved to: {ocr_path}")
    return ocr_text


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 4 FT: Alignment using Claude aligner (sub-part aware)
# ══════════════════════════════════════════════════════════════════════════════

def run_stage_4_FT(schema_with_answers: dict, ocr_text: str) -> dict:
    """
    Align student OCR text to the FT schema using the Claude aligner.
    The schema already has Q1a / Q1b / Q1c as separate keys, so the aligner
    will map each handwritten sub-part to its own slot naturally.
    """
    print("\n" + "=" * 60)
    print("STAGE 4 FT: Answer Alignment (Claude)")
    print("=" * 60)

    from claude_grading.answer_aligner_claude import align_answers_to_schema_claude

    # Parse OCR into pages list
    pages = []
    blocks = ocr_text.split("=== Page ")
    for block in blocks:
        if not block.strip():
            continue
        try:
            header, content = block.split("===", 1)
            page_num = int(header.strip())
            pages.append({"page": page_num, "text": content.strip()})
        except Exception:
            pass

    print(f"Parsed {len(pages)} OCR pages")
    print("Aligning student answers to FT schema (Claude Sonnet 4)...")

    aligned = align_answers_to_schema_claude(pages, schema_with_answers)

    aligned_path = os.path.join(PIPELINE_OUTPUT, "aligned_answers.json")
    with open(aligned_path, "w", encoding="utf-8") as f:
        json.dump(aligned, f, indent=2, ensure_ascii=False)
    print(f"✓ Aligned answers saved to: {aligned_path}")

    return aligned


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 5 FT: Grade + apply top-5-question scoring rule
# ══════════════════════════════════════════════════════════════════════════════

def _detect_attempted_questions(aligned: dict) -> dict[str, bool]:
    """
    Determine which Section B main questions (Q1–Q6) have a non-trivial student answer.
    Returns dict { "Q1": True, "Q2": False, ... }.
    A question is 'attempted' if any of its sub-parts has a student_answer with
    meaningful text (>= 20 alphabetic characters).
    """
    import unicodedata

    def has_meaningful_text(text: str) -> bool:
        if not text:
            return False
        letters = "".join(ch for ch in text if unicodedata.category(ch).startswith("L"))
        return len(letters) >= 20

    student_data = aligned.get("aligned_answers", aligned)
    section_b = student_data.get("SectionB", {})
    if not section_b:
        section_b = student_data.get("PART_I", {})
    attempted: dict[str, bool] = {}

    for q_key, q_content in section_b.items():
        if not isinstance(q_content, dict):
            continue
        answered = False
        for sub_key, sub_val in q_content.items():
            if isinstance(sub_val, dict):
                ans = sub_val.get("student_answer", "")
                if has_meaningful_text(str(ans)):
                    answered = True
                    break
        attempted[q_key] = answered

    return attempted


def _apply_top5_scoring(grading_results: dict, compulsory_q: str = "Q1", paper_meta: dict = None) -> dict:
    """
    Applies scoring rules.
    For standard Full Tests (100 marks): Q1 is compulsory, best 4 of Q2-Q6 are counted.
    For Portionwise Tests (e.g., 50 marks): All answered questions are counted, no exclusions.
    """
    if paper_meta is None:
        paper_meta = {}

    graded = grading_results.get("graded_answers", {})
    section_b = graded.get("SectionB", {})
    if not section_b:
        section_b = graded.get("PART_I", {})

    total_possible = float(paper_meta.get("total_marks_in_paper") or paper_meta.get("total_marks_printed") or 100)
    is_portionwise = total_possible < 100 or "portionwise" in str(paper_meta.get("paper_num", "")).lower()

    def q_total_obtained(q_content: dict) -> float:
        if "marks_obtained" in q_content:
            return float(q_content.get("marks_obtained", 0))
        total = 0.0
        for v in q_content.values():
            if isinstance(v, dict) and "marks_obtained" in v:
                total += float(v.get("marks_obtained", 0))
        return total

    # Separate compulsory and optional
    optional_scores: list[tuple[str, float]] = []
    for q_key, q_content in section_b.items():
        if q_key == compulsory_q:
            continue
        score = q_total_obtained(q_content)
        optional_scores.append((q_key, score))

    # If it's a portionwise test, we count EVERYTHING and exclude NOTHING.
    if is_portionwise:
        top4_keys = {k for k, _ in optional_scores}
        excluded_keys = set()
    else:
        # Standard FT Top-5 logic
        optional_scores.sort(key=lambda x: x[1], reverse=True)
        top4_keys = {k for k, _ in optional_scores[:4]}
        excluded_keys = {k for k, _ in optional_scores[4:]}

    # Flag excluded questions
    for q_key in excluded_keys:
        for sub_key, sub_val in section_b.get(q_key, {}).items():
            if isinstance(sub_val, dict):
                sub_val["excluded_from_total"] = True
                sub_val["exclusion_reason"] = (
                    f"{q_key} not counted: lower-scoring optional question excluded under top-4 rule"
                )

    # Recalculate totals
    total_obtained = 0.0

    # Section A MCQs
    section_a = graded.get("SectionA", {})
    for mcq_key, mcq_val in section_a.get("MCQ", {}).items():
        if isinstance(mcq_val, dict):
            total_obtained += float(mcq_val.get("marks_obtained", 0))

    # Section B: compulsory + top 4 optional (or all if portionwise)
    counted_keys = {compulsory_q} | top4_keys
    # For portionwise, the compulsory_q "Q1" might not exist or might just be a regular question
    if is_portionwise:
        counted_keys = set(section_b.keys())
        
    for q_key in counted_keys:
        q_content = section_b.get(q_key, {})
        total_obtained += q_total_obtained(q_content)

    percentage = round((total_obtained / float(total_possible)) * 100, 2) if total_possible > 0 else 0.0

    grading_results["metadata"]["total_marks_possible"] = total_possible
    grading_results["metadata"]["total_marks_obtained"] = round(total_obtained, 2)
    grading_results["metadata"]["percentage"] = percentage
    grading_results["metadata"]["grade"] = _calculate_grade(percentage)
    
    if is_portionwise:
        grading_results["metadata"]["scoring_rule"] = f"Portionwise Test: All questions counted. Total /{total_possible}."
    else:
        grading_results["metadata"]["scoring_rule"] = (
            f"FT: Q1 compulsory + top 4 of Q2-Q6 by marks obtained. "
            f"Excluded: {sorted(excluded_keys) or 'none'}. Total /{total_possible}."
        )
        
    grading_results["metadata"]["top5_questions"] = sorted(counted_keys)
    grading_results["metadata"]["excluded_questions"] = sorted(excluded_keys)

    print(f"\n  Scoring applied ({'Portionwise' if is_portionwise else 'FT Top-5'}):")
    print(f"    Counted questions : {sorted(counted_keys)}")
    if excluded_keys:
        print(f"    Excluded questions: {sorted(excluded_keys)}")
    print(f"    Total obtained    : {total_obtained:.1f} / 100")
    print(f"    Percentage        : {percentage}%")

    return grading_results


def _calculate_grade(percentage: float) -> str:
    if percentage >= 60: return "A"
    elif percentage >= 50: return "B"
    elif percentage >= 40: return "C"
    elif percentage >= 33: return "D"
    else: return "F"


def run_stage_5_FT(aligned: dict) -> dict:
    """
    Grade all answers (MCQ + sub-parts), then apply FT top-5 scoring rule.
    Uses the Claude grader (answer_grader_claude).
    """
    print("\n" + "=" * 60)
    print("STAGE 5 FT: Grading (sub-part level) + Top-5 scoring")
    print("=" * 60)

    from claude_grading.answer_grader_claude import grade_all_answers

    print("Grading sub-part answers with Claude Sonnet 4...")
    grading_results = grade_all_answers(
        aligned_answers=aligned,
        model_answers=aligned
    )

    # Apply FT top-5 scoring rule or Portionwise straight summation
    grading_results = _apply_top5_scoring(
        grading_results, 
        compulsory_q="Q1", 
        paper_meta=aligned.get("paper_meta", {})
    )

    # Save raw grading
    grading_path = os.path.join(GRADING_RESULTS, "grading_final.json")
    os.makedirs(GRADING_RESULTS, exist_ok=True)
    with open(grading_path, "w", encoding="utf-8") as f:
        json.dump(grading_results, f, indent=2, ensure_ascii=False)

    print(f"✓ Grading results saved to: {grading_path}")
    meta = grading_results.get("metadata", {})
    print(f"  Score: {meta.get('total_marks_obtained', 0)}/{meta.get('total_marks_possible', 100)}")
    print(f"  Percentage: {meta.get('percentage', 0):.2f}%")
    print(f"  Grade: {meta.get('grade', 'N/A')}")

    return grading_results


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="CheckerAI FT Pipeline — Full-Test paper grading with sub-part level grading"
    )
    parser.add_argument(
        "--FT", "--PT", dest="ft_paper_json", required=True,
        help="Path to the FT/PT paper JSON (e.g. AA_Mock_Paper_3.json or TAX_Portionwise_Test_1.json)"
    )
    parser.add_argument(
        "--as", dest="as_pdf", required=True,
        help="Student Answer Sheet PDF (used for Stage 7 annotation only)"
    )
    parser.add_argument(
        "--dataset", default=None,
        help="Dataset ID — used to locate the existing ocr_output.txt and save results"
    )
    parser.add_argument(
        "--skip-to", type=int, default=1,
        help=(
            "Skip to stage N. "
            "1=full run, 4=skip schema+OCR (load schema+OCR from disk), "
            "5=skip alignment (load aligned_answers from disk), "
            "6=skip grading (just re-run report+checked copy)"
        )
    )

    args = parser.parse_args()

    # Resolve dataset dir
    dataset_id = args.dataset
    if not dataset_id:
        basename = os.path.splitext(os.path.basename(args.as_pdf))[0]
        dataset_id = "".join(c for c in basename if c.isdigit()) or "FT_default"

    dataset_dir = os.path.join(GRADING_RESULTS, f"dataset_{dataset_id}")
    os.makedirs(dataset_dir, exist_ok=True)

    print("=" * 60)
    print(f"  CHECKERAI FT GRADING PIPELINE")
    print(f"  Dataset    : {dataset_id}")
    print(f"  FT Paper   : {args.ft_paper_json}")
    print(f"  Student AS : {args.as_pdf}")
    print(f"  Dataset dir: {dataset_dir}")
    print("=" * 60)

    start_time = time.time()
    ensure_dirs()

    try:
        # ── STAGE 1+2 FT: Build schema from paper JSON ────────────────────────
        if args.skip_to <= 2:
            schema_with_answers = run_stage_1_2_FT(args.ft_paper_json)
        else:
            swa_path = os.path.join(PIPELINE_OUTPUT, "schema_with_answers.json")
            with open(swa_path, "r", encoding="utf-8") as f:
                schema_with_answers = json.load(f)
            print(f"[SKIP] Stages 1+2 — loaded schema_with_answers from {swa_path}")

        # ── STAGE 3 FT: Load existing OCR ────────────────────────────────────
        if args.skip_to <= 3:
            ocr_text = run_stage_3_FT(dataset_dir, args.as_pdf)
        else:
            ocr_path_temp = os.path.join(PIPELINE_TEMP, "3_ocr_output.txt")
            ocr_path_ds   = os.path.join(dataset_dir, "ocr_output.txt")
            for p in [ocr_path_ds, ocr_path_temp]:
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as f:
                        ocr_text = f.read()
                    print(f"[SKIP] Stage 3 — loaded OCR from {p}")
                    break
            else:
                raise FileNotFoundError(f"No OCR file found. Run without --skip-to >= 4 first.")

        # ── STAGE 4 FT: Alignment ─────────────────────────────────────────────
        if args.skip_to <= 4:
            aligned = run_stage_4_FT(schema_with_answers, ocr_text)
        else:
            aligned_path = os.path.join(PIPELINE_OUTPUT, "aligned_answers.json")
            if not os.path.exists(aligned_path):
                aligned_path = os.path.join(dataset_dir, "aligned_answers.json")
            with open(aligned_path, "r", encoding="utf-8") as f:
                aligned = json.load(f)
            print(f"[SKIP] Stage 4 — loaded aligned from {aligned_path}")

        # ── STAGE 5 FT: Grade + top-5 scoring ────────────────────────────────
        if args.skip_to <= 5:
            grading_results = run_stage_5_FT(aligned)
        else:
            grading_path = os.path.join(GRADING_RESULTS, "grading_final.json")
            print(f"[SKIP] Stage 5 — using existing {grading_path}")

        # ── Copy all results to dataset dir ───────────────────────────────────
        print(f"\nCopying results to {dataset_dir}...")
        if args.skip_to <= 2:
            for fname in ["schema.json", "schema_with_answers.json"]:
                src = os.path.join(PIPELINE_OUTPUT, fname)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(dataset_dir, fname))
                    
        if args.skip_to <= 4:
            src = os.path.join(PIPELINE_OUTPUT, "aligned_answers.json")
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(dataset_dir, "aligned_answers.json"))
        # Copy OCR to dataset dir if not already there
        src_ocr = os.path.join(PIPELINE_TEMP, "3_ocr_output.txt")
        dest_ocr = os.path.join(dataset_dir, "ocr_output.txt")
        if os.path.exists(src_ocr) and not os.path.exists(dest_ocr):
            shutil.copy2(src_ocr, dest_ocr)
        # Grading final
        grading_src = os.path.join(GRADING_RESULTS, "grading_final.json")
        if os.path.exists(grading_src) and args.skip_to <= 5:
            shutil.copy2(grading_src, os.path.join(dataset_dir, "grading_final.json"))

        # ── STAGE 6: PDF grading report ───────────────────────────────────────
        run_stage_6(dataset_dir)

        # ── STAGE 7: Annotated checked copy (all questions marked) ───────────
        run_stage_7(as_path=args.as_pdf, dataset_dir=dataset_dir)

        # ── STAGE 8: Student report ───────────────────────────────────────────
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
        print(f"  ✓ FT PIPELINE COMPLETE in {elapsed:.1f}s")
        print(f"  Results: {dataset_dir}/")
        print(f"    grading_final.json   — sub-part grading + top-5 scoring")
        print(f"    grading_report.pdf   — teacher grading report")
        print(f"    checked_copy.pdf     — annotated student answer sheet (all questions)")
        print(f"    student_report.txt   — student performance report")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ FT PIPELINE FAILED: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
