#!/usr/bin/env python3
"""
Claude Grading Pipeline Runner — API Edition
=============================================
Copy of run_pipeline_claude.py, modified to work as a subprocess called by
the CheckerAI FastAPI backend.

Key changes vs. the original:
  --output-dir  Required.  All results are written here (no shared
                pipeline_output / pipeline_temp directories that would clash
                when multiple jobs run simultaneously).
  result.json   Written to --output-dir throughout the run so the API can
                poll for progress and the final output paths.

All other logic is identical to run_pipeline_claude.py.
"""
import os
import sys
import json
import argparse
import time
import shutil
import traceback
import uuid

# ── Path setup ───────────────────────────────────────────────────────────────
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
PIPELINE_DIR = os.path.join(os.path.dirname(BASE_DIR), "CA_Feedback_Pipeline")

sys.path.insert(0, BASE_DIR)
sys.path.insert(0, PIPELINE_DIR)

from dotenv import load_dotenv
load_dotenv()


# ── Status helpers ────────────────────────────────────────────────────────────

def _write_status(output_dir: str, stage: str, message: str, *, error: str = None, extra: dict = None):
    """Write/update result.json so the API can poll for progress."""
    data = {
        "stage":   stage,
        "message": message,
        "error":   error,
        "ts":      time.time(),
    }
    if extra:
        data.update(extra)
    path = os.path.join(output_dir, "result.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ── Stage helpers (isolated per-job, no shared directories) ──────────────────

def run_stage_1_isolated(qp_path: str, output_dir: str) -> dict:
    """Extract question schema from QP PDF — writes schema.json to output_dir."""
    print("\n" + "=" * 60)
    print("STAGE 1: Question Schema Extraction")
    print("=" * 60)

    from run_pipeline import extract_pdf_text_pymupdf
    from app.services.solution_schema_builder import build_solution_schema

    print("Extracting text from QP…")
    qp_text = extract_pdf_text_pymupdf(qp_path)
    qp_text_path = os.path.join(output_dir, "1_qp_text.txt")
    with open(qp_text_path, "w", encoding="utf-8") as f:
        f.write(qp_text)

    print("Building schema (AI-powered)…")
    schema = build_solution_schema(qp_text)

    schema_path = os.path.join(output_dir, "schema.json")
    with open(schema_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
    print(f"✓ Schema saved: {schema_path}")
    return schema


def run_stage_2_isolated(sa_path: str, schema: dict, output_dir: str) -> dict:
    """Extract model answers from solution PDF — Claude Sonnet 4."""
    print("\n" + "=" * 60)
    print("STAGE 2: Model Answer Extraction (CLAUDE SONNET 4)")
    print("=" * 60)

    from claude_grading.model_answer_builder_claude import (
        build_model_answers_claude,
        extract_pdf_text_tesseract,
    )

    sa_text = extract_pdf_text_tesseract(sa_path)
    sa_text_path = os.path.join(output_dir, "2_sa_text.txt")
    with open(sa_text_path, "w", encoding="utf-8") as f:
        f.write(sa_text)

    schema_with_answers = build_model_answers_claude(schema, sa_text, pdf_path=sa_path)
    swa_path = os.path.join(output_dir, "schema_with_answers.json")
    with open(swa_path, "w", encoding="utf-8") as f:
        json.dump(schema_with_answers, f, indent=2, ensure_ascii=False)
    print(f"✓ Schema-with-answers saved: {swa_path}")
    return schema_with_answers


def run_stage_3_isolated(as_pdf: str, output_dir: str) -> str:
    """OCR student answer sheet — Claude Vision."""
    print("\n" + "=" * 60)
    print("STAGE 3: OCR Extraction (CLAUDE VISION)")
    print("=" * 60)

    from claude_grading.ocr_service_claude import ocr_pdf_claude

    ocr_path = os.path.join(output_dir, "3_ocr_output.txt")
    ocr_text  = ocr_pdf_claude(as_pdf, output_path=ocr_path)
    print(f"✓ OCR saved: {ocr_path}")
    return ocr_text


def run_stage_4_isolated(schema_with_answers: dict, ocr_text: str, output_dir: str) -> dict:
    """Align student answers to schema — Claude Sonnet 4."""
    print("\n" + "=" * 60)
    print("STAGE 4: Answer Alignment (CLAUDE SONNET 4)")
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


def run_stage_5_isolated(aligned: dict, output_dir: str) -> dict:
    """Grade answers — Claude Sonnet 4."""
    print("\n" + "=" * 60)
    print("STAGE 5: Grading (CLAUDE SONNET 4)")
    print("=" * 60)

    from claude_grading.answer_grader_claude import grade_all_answers

    grading_results = grade_all_answers(aligned_answers=aligned, model_answers=aligned)

    grading_path = os.path.join(output_dir, "grading_final.json")
    with open(grading_path, "w", encoding="utf-8") as f:
        json.dump(grading_results, f, indent=2, ensure_ascii=False)
    print(f"✓ Grading saved: {grading_path}")

    meta = grading_results.get("metadata", {})
    print(f"  Score: {meta.get('total_marks_obtained', 0)}/{meta.get('total_marks_possible', 0)}")
    print(f"  Percentage: {meta.get('percentage', 0):.2f}%  Grade: {meta.get('grade', 'N/A')}")
    return grading_results


def run_stage_6_isolated(output_dir: str):
    from generate_grading_pdf import generate_pdf
    grading_path = os.path.join(output_dir, "grading_final.json")
    report_path  = os.path.join(output_dir, "grading_report.pdf")
    generate_pdf(json_path=grading_path, output_path=report_path)
    print(f"✓ Grading report saved: {report_path}")


def run_stage_7_isolated(as_path: str, output_dir: str):
    from generate_checked_copy_v2 import generate_checked_copy
    grading_path  = os.path.join(output_dir, "grading_final.json")
    aligned_path  = os.path.join(output_dir, "aligned_answers.json")
    output_path   = os.path.join(output_dir, "checked_copy.pdf")
    ocr_text_path = os.path.join(output_dir, "3_ocr_output.txt")

    generate_checked_copy(
        pdf_path=as_path,
        grading_json=grading_path,
        aligned_json=aligned_path,
        output_path=output_path,
        ocr_text_path=ocr_text_path if os.path.exists(ocr_text_path) else None,
    )
    print(f"✓ Checked copy saved: {output_path}")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="CheckerAI Old-Papers Grading Pipeline (Claude) — API Edition"
    )
    parser.add_argument("--qp",         required=True, help="Question Paper PDF")
    parser.add_argument("--sa",         required=True, help="Solution / Model Answer PDF")
    parser.add_argument("--as",  dest="as_pdf", required=True, help="Student Answer Sheet PDF")
    parser.add_argument("--output-dir", required=True,
                        help="Directory where ALL results are written (one per job)")
    parser.add_argument("--dataset",    default=None,  help="Dataset label (optional, for logging)")
    parser.add_argument("--skip-to",    type=int, default=1,
                        help="Skip to stage N (1=full run, 3=skip schema+MA, 4=skip+OCR, 5=skip alignment)")
    args = parser.parse_args()

    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    dataset_label = args.dataset or os.path.splitext(os.path.basename(args.as_pdf))[0]

    print("=" * 60)
    print("  CHECKERAI OLD-PAPERS GRADING PIPELINE (Claude Sonnet 4) — API")
    print(f"  Dataset    : {dataset_label}")
    print(f"  QP         : {args.qp}")
    print(f"  SA         : {args.sa}")
    print(f"  AS         : {args.as_pdf}")
    print(f"  Output dir : {output_dir}")
    print("=" * 60)

    _write_status(output_dir, "started", "Pipeline started")
    start = time.time()

    try:
        # ── Stage 1 ──
        if args.skip_to <= 1:
            _write_status(output_dir, "stage_1", "Extracting question schema from Question Paper…")
            schema = run_stage_1_isolated(args.qp, output_dir)
        else:
            with open(os.path.join(output_dir, "schema.json")) as f:
                schema = json.load(f)
            print("[SKIP] Stage 1")

        # ── Stage 2 ──
        if args.skip_to <= 2:
            _write_status(output_dir, "stage_2", "Extracting model answers from Solution PDF…")
            schema_with_answers = run_stage_2_isolated(args.sa, schema, output_dir)
        else:
            with open(os.path.join(output_dir, "schema_with_answers.json")) as f:
                schema_with_answers = json.load(f)
            print("[SKIP] Stage 2")

        # ── Stage 3 ──
        if args.skip_to <= 3:
            _write_status(output_dir, "stage_3", "Running Claude Vision OCR on student answer sheet…")
            ocr_text = run_stage_3_isolated(args.as_pdf, output_dir)
        else:
            for p in [os.path.join(output_dir, "3_ocr_output.txt"),
                      os.path.join(output_dir, "ocr_output.txt")]:
                if os.path.exists(p):
                    with open(p) as f:
                        ocr_text = f.read()
                    print(f"[SKIP] Stage 3 — loaded from {p}")
                    break

        # ── Stage 4 ──
        if args.skip_to <= 4:
            _write_status(output_dir, "stage_4", "Aligning student answers to schema…")
            aligned = run_stage_4_isolated(schema_with_answers, ocr_text, output_dir)
        else:
            with open(os.path.join(output_dir, "aligned_answers.json")) as f:
                aligned = json.load(f)
            print("[SKIP] Stage 4")

        # ── Stage 5 ──
        if args.skip_to <= 5:
            _write_status(output_dir, "stage_5", "Grading answers with Claude Sonnet 4…")
            grading_results = run_stage_5_isolated(aligned, output_dir)
        else:
            with open(os.path.join(output_dir, "grading_final.json")) as f:
                grading_results = json.load(f)
            print("[SKIP] Stage 5")

        # ── Stage 6: PDF Report ──
        _write_status(output_dir, "stage_6", "Generating PDF grading report…")
        try:
            run_stage_6_isolated(output_dir)
        except Exception as e:
            print(f"[WARN] Stage 6 skipped: {e}")

        # ── Stage 7: Checked copy ──
        _write_status(output_dir, "stage_7", "Annotating checked copy PDF…")
        try:
            run_stage_7_isolated(args.as_pdf, output_dir)
        except Exception as e:
            print(f"[WARN] Stage 7 skipped: {e}")

        # ── Stage 8: Student Report ──
        _write_status(output_dir, "stage_8", "Generating student performance report…")
        try:
            from generate_student_report import generate_student_report
            generate_student_report(
                grading_json_path=os.path.join(output_dir, "grading_final.json"),
                dataset_dir=output_dir,
                dataset_id=dataset_label
            )
            print(f"✓ Student report saved: {os.path.join(output_dir, 'student_report.txt')}")
        except Exception as e:
            print(f"[WARN] Stage 8 skipped: {e}")

        elapsed = time.time() - start
        meta = grading_results.get("metadata", {})

        _write_status(output_dir, "completed", f"Pipeline completed in {elapsed:.1f}s", extra={
            "checked_copy_pdf":  os.path.join(output_dir, "checked_copy.pdf"),
            "grading_report_pdf": os.path.join(output_dir, "grading_report.pdf"),
            "student_report_txt": os.path.join(output_dir, "student_report.txt"),
            "grading_json":      os.path.join(output_dir, "grading_final.json"),
            "total_marks_obtained": meta.get("total_marks_obtained"),
            "total_marks_possible": meta.get("total_marks_possible"),
            "percentage":           meta.get("percentage"),
            "grade":                meta.get("grade"),
        })

        print("\n" + "=" * 60)
        print(f"  ✓ PIPELINE COMPLETE in {elapsed:.1f}s  →  {output_dir}/")
        print("=" * 60)

    except Exception as e:
        _write_status(output_dir, "failed", "Pipeline failed", error=str(e))
        print(f"\n✗ PIPELINE FAILED: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
