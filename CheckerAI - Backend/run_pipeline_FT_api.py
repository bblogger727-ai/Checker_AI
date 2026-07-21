#!/usr/bin/env python3
"""
FT Grading Pipeline Runner — API Edition
=========================================
Copy of run_pipeline_FT.py, modified to work as a subprocess called by the
CheckerAI FastAPI backend.

Key changes vs. the original:
  --output-dir  Required.  All results (schema, OCR, grading, PDFs) are
                written here — no shared pipeline_output / pipeline_temp dirs,
                so multiple concurrent jobs don't collide.
  result.json   Written throughout the run for polling by the API.

All core logic (stage 1+2 FT, stage 3 FT, stage 4 FT, stage 5 FT + top-5
scoring, stage 6 report, stage 7 checked copy) is identical to the original.
"""
import os
import sys
import json
import argparse
import time
import shutil
import traceback
import unicodedata

# ── Path setup ───────────────────────────────────────────────────────────────
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
PIPELINE_DIR = os.path.join(os.path.dirname(BASE_DIR), "CA_Feedback_Pipeline")

sys.path.insert(0, BASE_DIR)
sys.path.insert(0, PIPELINE_DIR)

from dotenv import load_dotenv
load_dotenv()


# ── Status helpers ────────────────────────────────────────────────────────────

def _write_status(output_dir: str, stage: str, message: str, *, error: str = None, extra: dict = None):
    data = {"stage": stage, "message": message, "error": error, "ts": time.time()}
    if extra:
        data.update(extra)
    with open(os.path.join(output_dir, "result.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 1+2 FT  (identical logic, output_dir-aware)
# ══════════════════════════════════════════════════════════════════════════════

def run_stage_1_2_FT(ft_paper_json_path: str, output_dir: str) -> dict:
    print("\n" + "=" * 60)
    print("STAGE 1+2 FT: Building schema from FT paper JSON")
    print("=" * 60)

    with open(ft_paper_json_path, "r", encoding="utf-8") as f:
        paper = json.load(f)

    schema_with_answers: dict = {"paper_meta": paper.get("meta", {})}

    # Section A — MCQs
    section_a_raw  = paper.get("section_a", [])
    mcq_block: dict = {}
    serial_counter  = 0

    for case_study in section_a_raw:
        for q in case_study.get("questions", []):
            serial = q.get("_serial") or q.get("q_num")
            if serial is None:
                serial_counter += 1
                serial = serial_counter
            else:
                serial_counter = int(serial)

            key     = str(serial)
            correct = q.get("correct_option", q.get("answer", "")).strip("() ").lower()
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

    # Section B — Descriptive / sub-parts
    section_b_raw    = paper.get("section_b", [])
    section_b_block: dict = {}

    for main_q in section_b_raw:
        q_main      = main_q.get("q_main")
        q_key       = f"Q{q_main}"
        sub_q_block: dict = {}

        for sub in main_q.get("sub_questions", []):
            label   = sub.get("label", "")
            sub_key = f"Q{q_main}{label}"
            sub_q_block[sub_key] = {
                "question":        sub.get("question", ""),
                "model_answer":    sub.get("answer", ""),
                "marks":           sub.get("marks", 5),
                "question_number": sub_key,
                "chapter_number":  sub.get("chapter_number", ""),
                "chapter_name":    sub.get("chapter_name", ""),
            }

        section_b_block[q_key] = sub_q_block

    schema_with_answers["SectionB"] = section_b_block

    # Persist
    swa_path = os.path.join(output_dir, "schema_with_answers.json")
    with open(swa_path, "w", encoding="utf-8") as f:
        json.dump(schema_with_answers, f, indent=2, ensure_ascii=False)
    print(f"✓ schema_with_answers saved: {swa_path}")

    schema_meta_path = os.path.join(output_dir, "schema.json")
    with open(schema_meta_path, "w", encoding="utf-8") as f:
        json.dump({"paper_json": ft_paper_json_path, "meta": paper.get("meta", {})},
                  f, indent=2, ensure_ascii=False)

    return schema_with_answers


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 3 FT  (load existing OCR or run Claude Vision)
# ══════════════════════════════════════════════════════════════════════════════

def run_stage_3_FT(output_dir: str, as_pdf: str) -> str:
    print("\n" + "=" * 60)
    print("STAGE 3 FT: Loading or Extracting OCR")
    print("=" * 60)

    for path in [os.path.join(output_dir, "ocr_output.txt"),
                 os.path.join(output_dir, "ocr_output_claude.txt")]:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                ocr_text = f.read()
            print(f"✓ Loaded existing OCR: {path}  ({len(ocr_text):,} chars)")
            # mirror as standard name
            dest = os.path.join(output_dir, "3_ocr_output.txt")
            if path != dest:
                shutil.copy2(path, dest)
            return ocr_text

    print("No existing OCR — running Claude Vision OCR…")
    from claude_grading.ocr_service_claude import ocr_pdf_claude

    ocr_path = os.path.join(output_dir, "3_ocr_output.txt")
    ocr_text  = ocr_pdf_claude(as_pdf, output_path=ocr_path)
    # also save with canonical name
    shutil.copy2(ocr_path, os.path.join(output_dir, "ocr_output.txt"))
    print(f"✓ OCR completed: {ocr_path}")
    return ocr_text


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 4 FT  (Claude aligner, sub-part aware)
# ══════════════════════════════════════════════════════════════════════════════

def run_stage_4_FT(schema_with_answers: dict, ocr_text: str, output_dir: str) -> dict:
    print("\n" + "=" * 60)
    print("STAGE 4 FT: Answer Alignment (Claude)")
    print("=" * 60)

    from claude_grading.answer_aligner_claude import align_answers_to_schema_claude

    pages = []
    for block in ocr_text.split("=== Page "):
        if not block.strip():
            continue
        try:
            header, content = block.split("===", 1)
            pages.append({"page": int(header.strip()), "text": content.strip()})
        except Exception:
            pass

    print(f"Parsed {len(pages)} OCR pages")
    aligned = align_answers_to_schema_claude(pages, schema_with_answers)

    aligned_path = os.path.join(output_dir, "aligned_answers.json")
    with open(aligned_path, "w", encoding="utf-8") as f:
        json.dump(aligned, f, indent=2, ensure_ascii=False)
    print(f"✓ Aligned answers saved: {aligned_path}")
    return aligned


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 5 FT  (grade + top-5 scoring — verbatim from original)
# ══════════════════════════════════════════════════════════════════════════════

def _calculate_grade(pct: float) -> str:
    if pct >= 60: return "A"
    elif pct >= 50: return "B"
    elif pct >= 40: return "C"
    elif pct >= 33: return "D"
    else: return "F"


def _apply_top5_scoring(grading_results: dict, compulsory_q: str = "Q1",
                         paper_meta: dict = None) -> dict:
    if paper_meta is None:
        paper_meta = {}

    graded    = grading_results.get("graded_answers", {})
    section_b = graded.get("SectionB", {})

    total_possible = float(
        paper_meta.get("total_marks_in_paper") or
        paper_meta.get("total_marks_printed") or 100
    )
    is_portionwise = (
        total_possible < 100 or
        "portionwise" in str(paper_meta.get("paper_num", "")).lower()
    )

    def q_total_obtained(q_content: dict) -> float:
        return sum(
            float(v.get("marks_obtained", 0))
            for v in q_content.values()
            if isinstance(v, dict) and "marks_obtained" in v
        )

    optional_scores = [
        (k, q_total_obtained(v))
        for k, v in section_b.items()
        if k != compulsory_q
    ]

    if is_portionwise:
        top4_keys     = {k for k, _ in optional_scores}
        excluded_keys = set()
    else:
        optional_scores.sort(key=lambda x: x[1], reverse=True)
        top4_keys     = {k for k, _ in optional_scores[:4]}
        excluded_keys = {k for k, _ in optional_scores[4:]}

    for q_key in excluded_keys:
        for sub_val in section_b.get(q_key, {}).values():
            if isinstance(sub_val, dict):
                sub_val["excluded_from_total"] = True
                sub_val["exclusion_reason"] = (
                    f"{q_key} not counted: lower-scoring optional question excluded"
                )

    total_obtained = sum(
        float(v.get("marks_obtained", 0))
        for v in graded.get("SectionA", {}).get("MCQ", {}).values()
        if isinstance(v, dict)
    )

    counted_keys = {compulsory_q} | top4_keys
    if is_portionwise:
        counted_keys = set(section_b.keys())

    for q_key in counted_keys:
        total_obtained += q_total_obtained(section_b.get(q_key, {}))

    percentage = round((total_obtained / total_possible) * 100, 2) if total_possible else 0.0

    grading_results["metadata"]["total_marks_possible"] = total_possible
    grading_results["metadata"]["total_marks_obtained"] = round(total_obtained, 2)
    grading_results["metadata"]["percentage"]           = percentage
    grading_results["metadata"]["grade"]                = _calculate_grade(percentage)
    grading_results["metadata"]["scoring_rule"] = (
        f"Portionwise Test: All questions counted. Total /{total_possible}."
        if is_portionwise else
        f"FT: Q1 compulsory + top 4 of Q2-Q6. Excluded: {sorted(excluded_keys) or 'none'}."
    )
    grading_results["metadata"]["top5_questions"]     = sorted(counted_keys)
    grading_results["metadata"]["excluded_questions"] = sorted(excluded_keys)

    print(f"\n  Scoring ({'Portionwise' if is_portionwise else 'FT Top-5'}):")
    print(f"    Counted   : {sorted(counted_keys)}")
    if excluded_keys:
        print(f"    Excluded  : {sorted(excluded_keys)}")
    print(f"    Total     : {total_obtained:.1f}/{total_possible}  ({percentage}%)")

    return grading_results


def run_stage_5_FT(aligned: dict, output_dir: str) -> dict:
    print("\n" + "=" * 60)
    print("STAGE 5 FT: Grading (sub-part level) + Top-5 scoring")
    print("=" * 60)

    from claude_grading.answer_grader_claude import grade_all_answers

    grading_results = grade_all_answers(aligned_answers=aligned, model_answers=aligned)
    grading_results = _apply_top5_scoring(
        grading_results, compulsory_q="Q1",
        paper_meta=aligned.get("paper_meta", {})
    )

    grading_path = os.path.join(output_dir, "grading_final.json")
    with open(grading_path, "w", encoding="utf-8") as f:
        json.dump(grading_results, f, indent=2, ensure_ascii=False)
    print(f"✓ Grading saved: {grading_path}")
    return grading_results


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 6 & 7  (PDF report + checked copy)
# ══════════════════════════════════════════════════════════════════════════════

def run_stage_6_isolated(output_dir: str):
    from generate_grading_pdf import generate_pdf
    grading_path = os.path.join(output_dir, "grading_final.json")
    report_path  = os.path.join(output_dir, "grading_report.pdf")
    generate_pdf(json_path=grading_path, output_path=report_path)
    print(f"✓ Grading report saved: {report_path}")


def run_stage_7_isolated(as_path: str, output_dir: str):
    from generate_checked_copy_v2 import generate_checked_copy
    generate_checked_copy(
        pdf_path=as_path,
        grading_json=os.path.join(output_dir, "grading_final.json"),
        aligned_json=os.path.join(output_dir, "aligned_answers.json"),
        output_path=os.path.join(output_dir, "checked_copy.pdf"),
        ocr_text_path=os.path.join(output_dir, "3_ocr_output.txt"),
    )
    print(f"✓ Checked copy saved: {os.path.join(output_dir, 'checked_copy.pdf')}")

def run_stage_8_isolated(output_dir: str):
    from generate_student_report import generate_student_report
    generate_student_report(
        grading_json_path=os.path.join(output_dir, "grading_final.json"),
        dataset_dir=output_dir,
        dataset_id=os.path.basename(output_dir)
    )
    print(f"✓ Student report saved: {os.path.join(output_dir, 'student_report.txt')}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="CheckerAI FT Grading Pipeline — API Edition"
    )
    parser.add_argument("--FT", "--PT", dest="ft_paper_json", required=True,
                        help="Path to the FT/PT paper JSON (e.g. AA_Mock_Paper_3.json)")
    parser.add_argument("--as", dest="as_pdf", required=True,
                        help="Student Answer Sheet PDF")
    parser.add_argument("--output-dir", required=True,
                        help="Directory where ALL results are written (one per job)")
    parser.add_argument("--dataset", default=None,
                        help="Dataset label (optional, for logging)")
    parser.add_argument("--skip-to", type=int, default=1,
                        help="Skip to stage N (1=full, 4=skip schema+OCR, 5=skip align)")
    args = parser.parse_args()

    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    dataset_label = args.dataset or os.path.splitext(os.path.basename(args.as_pdf))[0]

    print("=" * 60)
    print("  CHECKERAI FT GRADING PIPELINE — API")
    print(f"  FT Paper   : {args.ft_paper_json}")
    print(f"  Student AS : {args.as_pdf}")
    print(f"  Output dir : {output_dir}")
    print("=" * 60)

    _write_status(output_dir, "started", "Pipeline started")
    start = time.time()

    try:
        # Stage 1+2 FT
        if args.skip_to <= 2:
            _write_status(output_dir, "stage_1_2", "Building schema from FT paper JSON…")
            schema_with_answers = run_stage_1_2_FT(args.ft_paper_json, output_dir)
        else:
            with open(os.path.join(output_dir, "schema_with_answers.json")) as f:
                schema_with_answers = json.load(f)
            print("[SKIP] Stages 1+2")

        # Stage 3 FT
        if args.skip_to <= 3:
            _write_status(output_dir, "stage_3", "Running OCR on student answer sheet…")
            ocr_text = run_stage_3_FT(output_dir, args.as_pdf)
        else:
            for p in [os.path.join(output_dir, "3_ocr_output.txt"),
                      os.path.join(output_dir, "ocr_output.txt")]:
                if os.path.exists(p):
                    with open(p) as f:
                        ocr_text = f.read()
                    print(f"[SKIP] Stage 3 — loaded from {p}")
                    break

        # Stage 4 FT
        if args.skip_to <= 4:
            _write_status(output_dir, "stage_4", "Aligning student answers…")
            aligned = run_stage_4_FT(schema_with_answers, ocr_text, output_dir)
        else:
            with open(os.path.join(output_dir, "aligned_answers.json")) as f:
                aligned = json.load(f)
            print("[SKIP] Stage 4")

        # Stage 5 FT
        if args.skip_to <= 5:
            _write_status(output_dir, "stage_5", "Grading with Claude Sonnet 4…")
            grading_results = run_stage_5_FT(aligned, output_dir)
        else:
            with open(os.path.join(output_dir, "grading_final.json")) as f:
                grading_results = json.load(f)
            print("[SKIP] Stage 5")

        # Stage 6
        _write_status(output_dir, "stage_6", "Generating PDF grading report…")
        try:
            run_stage_6_isolated(output_dir)
        except Exception as e:
            print(f"[WARN] Stage 6 skipped: {e}")

        # Stage 7
        _write_status(output_dir, "stage_7", "Annotating checked copy PDF…")
        try:
            run_stage_7_isolated(args.as_pdf, output_dir)
        except Exception as e:
            print(f"[WARN] Stage 7 skipped: {e}")

        # Stage 8
        _write_status(output_dir, "stage_8", "Generating student performance report…")
        try:
            run_stage_8_isolated(output_dir)
        except Exception as e:
            print(f"[WARN] Stage 8 skipped: {e}")

        elapsed = time.time() - start
        meta    = grading_results.get("metadata", {})

        _write_status(output_dir, "completed", f"Pipeline completed in {elapsed:.1f}s", extra={
            "checked_copy_pdf":      os.path.join(output_dir, "checked_copy.pdf"),
            "grading_report_pdf":    os.path.join(output_dir, "grading_report.pdf"),
            "student_report_txt":    os.path.join(output_dir, "student_report.txt"),
            "grading_json":          os.path.join(output_dir, "grading_final.json"),
            "total_marks_obtained":  meta.get("total_marks_obtained"),
            "total_marks_possible":  meta.get("total_marks_possible"),
            "percentage":            meta.get("percentage"),
            "grade":                 meta.get("grade"),
            "scoring_rule":          meta.get("scoring_rule"),
        })

        print("\n" + "=" * 60)
        print(f"  ✓ FT PIPELINE COMPLETE in {elapsed:.1f}s  →  {output_dir}/")
        print("=" * 60)

    except Exception as e:
        _write_status(output_dir, "failed", "Pipeline failed", error=str(e))
        print(f"\n✗ FT PIPELINE FAILED: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
