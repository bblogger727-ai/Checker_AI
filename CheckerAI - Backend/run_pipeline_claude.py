#!/usr/bin/env python3
"""
Claude Grading Pipeline Runner

Uses Claude Sonnet 4 for ALL stages (Schema, Model Answers, OCR, Alignment, Grading).
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

# claude_grading module lives in CA_Feedback_Pipeline/
PIPELINE_DIR = os.path.join(os.path.dirname(BASE_DIR), "CA_Feedback_Pipeline")
sys.path.insert(0, PIPELINE_DIR)

from dotenv import load_dotenv
load_dotenv()

# Pipeline directories (same as original pipeline)
PIPELINE_OUTPUT = os.path.join(BASE_DIR, "pipeline_output")
PIPELINE_TEMP = os.path.join(BASE_DIR, "pipeline_temp")
GRADING_RESULTS = os.path.join(BASE_DIR, "grading_results")


# ==============================================================
# Import Stages 1, 3, 6, 7 from the original pipeline (OpenAI)
# ==============================================================
from run_pipeline import (
    ensure_dirs,
    clear_temp,
    run_stage_1,
    run_stage_3,
    run_stage_6,
    run_stage_7,
)
from generate_student_report import generate_student_report


# ==============================================================
# STAGE 2: Model Answer Extraction (CLAUDE SONNET 4)
# ==============================================================
def run_stage_2_claude(sa_path: str, schema: dict) -> dict:
    print("\n" + "=" * 60)
    print("STAGE 2: Model Answer Extraction (CLAUDE SONNET 4)")
    print("=" * 60)
    print(f"Solution PDF: {sa_path}")

    from claude_grading.model_answer_builder_claude import (
        build_model_answers_claude,
        extract_pdf_text_tesseract,
    )

    # Extract SA text with Tesseract (same as original)
    print("Extracting text from SA (Tesseract OCR for tables)...")
    sa_text = extract_pdf_text_tesseract(sa_path)

    # Save for debugging
    sa_text_path = os.path.join(PIPELINE_TEMP, "2_sa_text.txt")
    with open(sa_text_path, "w") as f:
        f.write(sa_text)
    print(f"✓ Saved SA text to: {sa_text_path}")

    # Build model answers using Claude
    print("Extracting model answers (Claude Sonnet 4 text extraction + OpenAI vision)...")
    schema_with_answers = build_model_answers_claude(schema, sa_text, pdf_path=sa_path)

    # Save
    complete_path = os.path.join(PIPELINE_OUTPUT, "schema_with_answers.json")
    with open(complete_path, "w") as f:
        json.dump(schema_with_answers, f, indent=2, ensure_ascii=False)
    print(f"✓ Schema with answers saved to: {complete_path}")

    return schema_with_answers


# ==============================================================
# STAGE 3: OCR Data Extraction (CLAUDE SONNET 4)
# ==============================================================
def run_stage_3_claude(as_pdf: str) -> str:
    print("\n" + "=" * 60)
    print("STAGE 3: OCR Extraction (CLAUDE VISION)")
    print("=" * 60)

    from claude_grading.ocr_service_claude import ocr_pdf_claude

    print(f"Extracting handwritten text from student answer sheet: {as_pdf}")
    print("Using Claude Sonnet 4 Vision (this may take a few minutes for a long PDF)...")
    
    ocr_path = os.path.join(PIPELINE_TEMP, "3_ocr_output.txt")
    ocr_text = ocr_pdf_claude(as_pdf, output_path=ocr_path)
    
    print(f"✓ OCR completed. Saved to: {ocr_path}")
    return ocr_text


# ==============================================================
# STAGE 4: Answer Alignment (CLAUDE SONNET 4)
# ==============================================================
def run_stage_4_claude(schema_with_answers: dict, ocr_text: str) -> dict:
    print("\n" + "=" * 60)
    print("STAGE 4: Answer Alignment (CLAUDE SONNET 4)")
    print("=" * 60)
    
    from claude_grading.answer_aligner_claude import align_answers_to_schema_claude
    
    print("Parsing OCR text...")
    pages = []
    # OCR text uses "=== Page 1 ===" formatting
    blocks = ocr_text.split("=== Page ")
    for block in blocks:
        if not block.strip():
            continue
        try:
            # block looks like "1 ===\nText content..."
            header, content = block.split("===", 1)
            page_num = int(header.strip())
            pages.append({"page": page_num, "text": content.strip()})
        except:
            pass
            
    print(f"Parsed {len(pages)} pages")
    print("Aligning student answers to schema (Claude Sonnet 4)...")
    
    aligned = align_answers_to_schema_claude(pages, schema_with_answers)
    
    aligned_path = os.path.join(PIPELINE_OUTPUT, "aligned_answers.json")
    with open(aligned_path, "w") as f:
        json.dump(aligned, f, indent=2, ensure_ascii=False)
    print(f"✓ Aligned answers saved to: {aligned_path}")
    
    return aligned


# ==============================================================
# STAGE 5: Grading (CLAUDE SONNET 4)
# ==============================================================
def run_stage_5_claude(aligned: dict) -> dict:
    print("\n" + "=" * 60)
    print("STAGE 5: Grading (Two-Phase System — CLAUDE SONNET 4)")
    print("=" * 60)

    from claude_grading.answer_grader_claude import grade_all_answers

    print("Grading answers with Claude Sonnet 4 (this may take a few minutes)...")
    grading_results = grade_all_answers(
        aligned_answers=aligned,
        model_answers=aligned
    )

    # Save to grading_results/
    grading_path = os.path.join(GRADING_RESULTS, "grading_final.json")
    with open(grading_path, "w") as f:
        json.dump(grading_results, f, indent=2, ensure_ascii=False)

    print(f"✓ Grading results saved to: {grading_path}")

    # Print summary
    if 'metadata' in grading_results:
        meta = grading_results['metadata']
        print(f"\n  Model: {meta.get('grading_model', 'Claude Sonnet 4')}")
        print(f"  Score: {meta.get('total_marks_obtained', 0)}/{meta.get('total_marks_possible', 0)}")
        print(f"  Percentage: {meta.get('percentage', 0):.2f}%")
        print(f"  Grade: {meta.get('grade', 'N/A')}")

    return grading_results


# ==============================================================
# MAIN: Run all stages
# ==============================================================
def main():
    parser = argparse.ArgumentParser(description='Run grading pipeline with Claude Sonnet 4')
    parser.add_argument('--qp', required=True, help='Question Paper PDF')
    parser.add_argument('--sa', required=True, help='Solution/Model Answer PDF')
    parser.add_argument('--as', dest='as_pdf', required=True, help='Student Answer Sheet PDF')
    parser.add_argument('--dataset', default=None, help='Dataset ID for organizing results')
    parser.add_argument('--skip-to', type=int, default=1, help='Skip to stage N (use cached results from earlier stages)')
    parser.add_argument('--skip-ocr', action='store_true', help='Skip OCR Stage 3 and use cached OCR if available')

    args = parser.parse_args()

    # Setup dataset dir
    dataset_id = args.dataset
    if not dataset_id:
        basename = os.path.splitext(os.path.basename(args.as_pdf))[0]
        dataset_id = ''.join(c for c in basename if c.isdigit()) or "default"

    dataset_dir = os.path.join(GRADING_RESULTS, f"dataset_{dataset_id}")
    os.makedirs(dataset_dir, exist_ok=True)

    print("=" * 60)
    print(f"  CHECKERAI GRADING PIPELINE (Claude Sonnet 4)")
    print(f"  Dataset: {dataset_id}")
    print(f"  QP: {args.qp}")
    print(f"  SA: {args.sa}")
    print(f"  AS: {args.as_pdf}")
    print(f"  Stages 1-5: CLAUDE | Stage 6: PDF Report | Stage 7: Checked Copy")
    print("=" * 60)

    start_time = time.time()
    ensure_dirs()

    if args.skip_to <= 1:
        clear_temp()

    try:
        # STAGE 1 (Claude)
        if args.skip_to <= 1:
            schema = run_stage_1(args.qp)
        else:
            schema_path = os.path.join(PIPELINE_OUTPUT, "schema.json")
            with open(schema_path, "r") as f:
                schema = json.load(f)
            print(f"[SKIP] Stage 1 — loaded schema from {schema_path}")

        # STAGE 2 (CLAUDE)
        if args.skip_to <= 2:
            schema_with_answers = run_stage_2_claude(args.sa, schema)
        else:
            swa_path = os.path.join(PIPELINE_OUTPUT, "schema_with_answers.json")
            with open(swa_path, "r") as f:
                schema_with_answers = json.load(f)
            print(f"[SKIP] Stage 2 — loaded schema_with_answers from {swa_path}")

        # STAGE 3 (CLAUDE)
        ocr_dataset_path = os.path.join(dataset_dir, "ocr_output_claude.txt")
        ocr_dataset_path_fallback = os.path.join(dataset_dir, "ocr_output.txt")
        
        if args.skip_to <= 3 and not args.skip_ocr:
            ocr_text = run_stage_3_claude(args.as_pdf)
        else:
            # Try to load from dataset dir first to preserve existing dataset OCR
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

        # STAGE 4 (CLAUDE)
        if args.skip_to <= 4:
            aligned = run_stage_4_claude(schema_with_answers, ocr_text)
        else:
            aligned_path = os.path.join(PIPELINE_OUTPUT, "aligned_answers.json")
            with open(aligned_path, "r") as f:
                aligned = json.load(f)
            print(f"[SKIP] Stage 4 — loaded aligned from {aligned_path}")

        # STAGE 5 (CLAUDE)
        if args.skip_to <= 5:
            grading_results = run_stage_5_claude(aligned)
        else:
            grading_path = os.path.join(GRADING_RESULTS, "grading_final.json")
            print(f"[SKIP] Stage 5 — using {grading_path}")

        # Copy all results to dataset dir
        print(f"\nCopying results to {dataset_dir}...")
        for fname in ["schema.json", "schema_with_answers.json", "aligned_answers.json"]:
            src = os.path.join(PIPELINE_OUTPUT, fname)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(dataset_dir, fname))
        for fname in ["3_ocr_output.txt"]:
            src = os.path.join(PIPELINE_TEMP, fname)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(dataset_dir, "ocr_output.txt"))
        grading_src = os.path.join(GRADING_RESULTS, "grading_final.json")
        if os.path.exists(grading_src) and args.skip_to <= 5:
            # Only copy when grading was freshly run — never overwrite user edits
            shutil.copy2(grading_src, os.path.join(dataset_dir, "grading_final.json"))

        # STAGE 6 (local PDF report)
        run_stage_6(dataset_dir)

        # STAGE 7 (annotated checked copy — student-facing PDF with marks & feedback)
        run_stage_7(as_path=args.as_pdf, dataset_dir=dataset_dir)

        # STAGE 8 (student performance DOCX report)
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
        print(f"  Graded by: Claude Sonnet 4")
        print(f"  Results: {dataset_dir}/")
        print(f"    grading_report.pdf   — teacher grading report")
        print(f"    checked_copy.pdf     — annotated student answer sheet")
        print(f"    student_report.txt   — student performance report")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ PIPELINE FAILED: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
