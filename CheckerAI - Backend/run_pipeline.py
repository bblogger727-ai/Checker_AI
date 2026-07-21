#!/usr/bin/env python3
"""
Unified Pipeline Runner
Runs all 6 stages end-to-end: Schema → Model Answers → OCR → Alignment → Grading → Report

Usage:
  python3 run_pipeline.py --qp QP.pdf --sa SA.pdf --as AS.pdf [--dataset DATASET_ID]
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

from dotenv import load_dotenv
load_dotenv()

# Pipeline directories (all relative to BASE_DIR)
PIPELINE_OUTPUT = os.path.join(BASE_DIR, "pipeline_output")
PIPELINE_TEMP = os.path.join(BASE_DIR, "pipeline_temp")
GRADING_RESULTS = os.path.join(BASE_DIR, "grading_results")


def ensure_dirs():
    """Create all pipeline directories."""
    for d in [PIPELINE_OUTPUT, PIPELINE_TEMP, GRADING_RESULTS]:
        os.makedirs(d, exist_ok=True)


def clear_temp():
    """Clear temp files from previous runs."""
    for fname in os.listdir(PIPELINE_TEMP):
        fpath = os.path.join(PIPELINE_TEMP, fname)
        if os.path.isfile(fpath):
            os.remove(fpath)
    # Also clear pipeline_output
    for fname in os.listdir(PIPELINE_OUTPUT):
        fpath = os.path.join(PIPELINE_OUTPUT, fname)
        if os.path.isfile(fpath):
            os.remove(fpath)


def extract_pdf_text_pymupdf(pdf_path: str) -> str:
    """Extract text from PDF using PyMuPDF."""
    import fitz
    doc = fitz.open(pdf_path)
    text = ""
    for page_num, page in enumerate(doc, 1):
        page_text = page.get_text()
        text += f"\n\n=== Page {page_num} ===\n{page_text}"
    doc.close()
    return text


# ==============================================================
# STAGE 1: Schema Generation
# ==============================================================
def run_stage_1(qp_path: str) -> dict:
    print("\n" + "=" * 60)
    print("STAGE 1: Schema Generation")
    print("=" * 60)
    print(f"Question Paper: {qp_path}")

    # Extract QP text
    print("Extracting text from QP...")
    qp_text = extract_pdf_text_pymupdf(qp_path)

    # Save for debugging
    qp_text_path = os.path.join(PIPELINE_TEMP, "1_qp_text.txt")
    with open(qp_text_path, "w") as f:
        f.write(qp_text)
    print(f"✓ Saved QP text to: {qp_text_path}")

    # Build schema
    print("Building schema (AI-powered)...")
    from app.services.solution_schema_builder import build_solution_schema
    schema = build_solution_schema(qp_text)

    # Save schema
    schema_path = os.path.join(PIPELINE_OUTPUT, "schema.json")
    with open(schema_path, "w") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
    print(f"✓ Schema saved to: {schema_path}")

    # Verify
    if not os.path.exists(schema_path):
        raise RuntimeError("Stage 1 FAILED: schema.json not written")

    return schema


# ==============================================================
# STAGE 2: Model Answer Extraction
# ==============================================================
def run_stage_2(sa_path: str, schema: dict) -> dict:
    print("\n" + "=" * 60)
    print("STAGE 2: Model Answer Extraction")
    print("=" * 60)
    print(f"Solution PDF: {sa_path}")

    from app.services.model_answer_builder import build_model_answers, extract_pdf_text_tesseract

    # Extract SA text with Tesseract
    print("Extracting text from SA (Tesseract OCR for tables)...")
    sa_text = extract_pdf_text_tesseract(sa_path)

    # Save for debugging
    sa_text_path = os.path.join(PIPELINE_TEMP, "2_sa_text.txt")
    with open(sa_text_path, "w") as f:
        f.write(sa_text)
    print(f"✓ Saved SA text to: {sa_text_path}")

    # Build model answers
    print("Extracting model answers (GPT-4o vision + text chunking)...")
    schema_with_answers = build_model_answers(schema, sa_text, pdf_path=sa_path)

    # Save
    complete_path = os.path.join(PIPELINE_OUTPUT, "schema_with_answers.json")
    with open(complete_path, "w") as f:
        json.dump(schema_with_answers, f, indent=2, ensure_ascii=False)
    print(f"✓ Schema with answers saved to: {complete_path}")

    return schema_with_answers


# ==============================================================
# STAGE 3: Student Answer OCR
# ==============================================================

# Phrases that indicate the API refused to OCR the page
OCR_REFUSAL_PHRASES = [
    "unable to extract",
    "i can't extract",
    "i cannot extract",
    "can't directly extract",
    "cannot directly extract",
    "ocr tools",
    "let me know how i can assist",
    "let me know how i can help",
    "i'm not able to",
    "i am not able to",
    "help you with any questions",
    "provide guidance on",
    "assist you with",
    "text extraction tool",
    "optical character recognition",
    "[OCR FAILED",
]


def is_ocr_refusal(page_text: str) -> bool:
    """Check if OCR output looks like an API refusal rather than actual extracted text."""
    text_lower = page_text.strip().lower()
    # Check for refusal phrases
    for phrase in OCR_REFUSAL_PHRASES:
        if phrase.lower() in text_lower:
            return True
    # Very short output (< 30 chars) for a full page is suspicious
    if len(text_lower) < 30:
        return True
    return False


def ocr_single_page(doc, page_num: int, perform_ocr_fn, dpi: int = 200) -> str:
    """OCR a single page with retry logic."""
    from PIL import Image
    page = doc[page_num]
    pix = page.get_pixmap(dpi=dpi)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            page_text = perform_ocr_fn(img)
            return page_text
        except Exception as e:
            if attempt == max_retries:
                print(f"    ✗ Page {page_num + 1} failed after {max_retries} attempts: {e}")
                return f"[OCR FAILED ON PAGE {page_num + 1}]"
            else:
                wait = attempt * 5
                print(f"    ⚠ Attempt {attempt} failed ({e}), retrying in {wait}s...")
                time.sleep(wait)
    return f"[OCR FAILED ON PAGE {page_num + 1}]"


def run_stage_3(as_path: str) -> str:
    print("\n" + "=" * 60)
    print("STAGE 3: Student Answer OCR")
    print("=" * 60)
    print(f"Student PDF: {as_path}")

    import fitz
    from app.services.ocr_service import perform_ocr

    doc = fitz.open(as_path)
    total_pages = len(doc)

    # ---- Pass 1: OCR all pages ----
    page_texts = {}
    for page_num in range(total_pages):
        print(f"  Processing page {page_num + 1}/{total_pages}...", flush=True)
        page_texts[page_num] = ocr_single_page(doc, page_num, perform_ocr, dpi=200)

    # ---- Pass 2: Validate & retry refused pages ----
    refused_pages = [p for p in range(total_pages) if is_ocr_refusal(page_texts[p])]
    if refused_pages:
        print(f"\n  ⚠ OCR refusal detected on {len(refused_pages)} page(s): {[p+1 for p in refused_pages]}")
        print(f"  Retrying with higher DPI (300)...")
        for page_num in refused_pages:
            print(f"    Re-processing page {page_num + 1}...", flush=True)
            retry_text = ocr_single_page(doc, page_num, perform_ocr, dpi=300)
            if not is_ocr_refusal(retry_text):
                page_texts[page_num] = retry_text
                print(f"    ✓ Page {page_num + 1} recovered ({len(retry_text)} chars)")
            else:
                # Try once more with even higher DPI
                print(f"    ⚠ Page {page_num + 1} still refused, trying DPI 400...")
                retry_text_2 = ocr_single_page(doc, page_num, perform_ocr, dpi=400)
                if not is_ocr_refusal(retry_text_2):
                    page_texts[page_num] = retry_text_2
                    print(f"    ✓ Page {page_num + 1} recovered ({len(retry_text_2)} chars)")
                else:
                    print(f"    ✗ Page {page_num + 1} could not be recovered after all retries")

    doc.close()

    # ---- Build final text ----
    all_text = ""
    for page_num in range(total_pages):
        all_text += f"\n=== Page {page_num + 1} ===\n```\n{page_texts[page_num]}\n```\n"

    # Save OCR output
    ocr_path = os.path.join(PIPELINE_TEMP, "3_ocr_output.txt")
    with open(ocr_path, "w") as f:
        f.write(all_text)

    # Final validation summary
    still_refused = [p+1 for p in range(total_pages) if is_ocr_refusal(page_texts[p])]
    if still_refused:
        print(f"\n  ⚠ WARNING: Pages {still_refused} still have OCR issues after retries")
    else:
        print(f"\n  ✓ All {total_pages} pages extracted successfully")

    print(f"✓ OCR output saved to: {ocr_path}")
    print(f"  Total chars: {len(all_text)}")

    return all_text


# ==============================================================
# STAGE 4: Answer Alignment
# ==============================================================
def run_stage_4(schema_with_answers: dict, ocr_text: str) -> dict:
    print("\n" + "=" * 60)
    print("STAGE 4: Answer Alignment")
    print("=" * 60)

    from app.services.answer_parser import parse_ocr_to_pages
    from app.services.answer_aligner import align_answers_to_schema

    # Parse OCR
    print("Parsing OCR text...")
    student_pages = parse_ocr_to_pages(ocr_text)
    print(f"Parsed {len(student_pages)} pages")

    # Align
    print("Aligning student answers to schema...")
    aligned = align_answers_to_schema(student_pages, schema_with_answers)

    # Save
    aligned_path = os.path.join(PIPELINE_OUTPUT, "aligned_answers.json")
    with open(aligned_path, "w") as f:
        json.dump(aligned, f, indent=2, ensure_ascii=False)

    print(f"✓ Aligned answers saved to: {aligned_path}")

    return aligned


# ==============================================================
# STAGE 5: Grading
# ==============================================================
def run_stage_5(aligned: dict) -> dict:
    print("\n" + "=" * 60)
    print("STAGE 5: Grading (Two-Phase System)")
    print("=" * 60)

    from app.services.answer_grader import grade_all_answers

    print("Grading answers (this may take a few minutes)...")
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
        print(f"\n  Score: {meta.get('total_marks_obtained', 0)}/{meta.get('total_marks_possible', 0)}")
        print(f"  Percentage: {meta.get('percentage', 0):.2f}%")
        print(f"  Grade: {meta.get('grade', 'N/A')}")

    return grading_results


# ==============================================================
# STAGE 6: Report Generation
# ==============================================================
def run_stage_6(dataset_dir: str = None):
    print("\n" + "=" * 60)
    print("STAGE 6: Report Generation")
    print("=" * 60)

    from generate_grading_pdf import generate_pdf

    grading_path = os.path.join(GRADING_RESULTS, "grading_final.json")
    report_path = os.path.join(GRADING_RESULTS, "grading_report.pdf")
    generate_pdf(json_path=grading_path, output_path=report_path)

    print(f"✓ Report saved to: {report_path}")

    # Copy to dataset dir if specified
    if dataset_dir:
        dest_report = os.path.join(dataset_dir, "grading_report.pdf")
        shutil.copy2(report_path, dest_report)
        print(f"✓ Report copied to: {dest_report}")


# ==============================================================
# STAGE 7: Checked Copy (Student-Facing Annotated PDF)
# ==============================================================
def run_stage_7(as_path: str, dataset_dir: str):
    print("\n" + "=" * 60)
    print("STAGE 7: Checked Copy Generation")
    print("=" * 60)

    from generate_checked_copy_v2 import generate_checked_copy

    grading_path  = os.path.join(dataset_dir, "grading_final.json")
    aligned_path  = os.path.join(dataset_dir, "aligned_answers.json")
    output_path   = os.path.join(dataset_dir, "checked_copy.pdf")
    ocr_text_path = os.path.join(dataset_dir, "ocr_output.txt")

    generate_checked_copy(
        pdf_path      = as_path,
        grading_json  = grading_path,
        aligned_json  = aligned_path,
        output_path   = output_path,
        ocr_text_path = ocr_text_path if os.path.exists(ocr_text_path) else None,
    )
    print(f"✓ Checked copy saved to: {output_path}")


# ==============================================================
# MAIN: Run all stages
# ==============================================================
def main():
    parser = argparse.ArgumentParser(description='Run full grading pipeline')
    parser.add_argument('--qp', required=True, help='Question Paper PDF')
    parser.add_argument('--sa', required=True, help='Solution/Model Answer PDF')
    parser.add_argument('--as', dest='as_pdf', required=True, help='Student Answer Sheet PDF')
    parser.add_argument('--dataset', default=None, help='Dataset ID for organizing results')
    parser.add_argument('--skip-to', type=int, default=1, help='Skip to stage N (use cached results from earlier stages)')

    args = parser.parse_args()

    # Setup dataset dir
    dataset_id = args.dataset
    if not dataset_id:
        # Extract from filename (e.g. 15145as.pdf → 15145)
        basename = os.path.splitext(os.path.basename(args.as_pdf))[0]
        dataset_id = ''.join(c for c in basename if c.isdigit()) or "default"

    dataset_dir = os.path.join(GRADING_RESULTS, f"dataset_{dataset_id}")
    os.makedirs(dataset_dir, exist_ok=True)

    print("=" * 60)
    print(f"  CHECKERAI GRADING PIPELINE")
    print(f"  Dataset: {dataset_id}")
    print(f"  QP: {args.qp}")
    print(f"  SA: {args.sa}")
    print(f"  AS: {args.as_pdf}")
    print("=" * 60)

    start_time = time.time()

    # Ensure directories
    ensure_dirs()

    # Clear only if running from stage 1
    if args.skip_to <= 1:
        clear_temp()

    try:
        # STAGE 1
        if args.skip_to <= 1:
            schema = run_stage_1(args.qp)
        else:
            schema_path = os.path.join(PIPELINE_OUTPUT, "schema.json")
            with open(schema_path, "r") as f:
                schema = json.load(f)
            print(f"[SKIP] Stage 1 — loaded schema from {schema_path}")

        # STAGE 2
        if args.skip_to <= 2:
            schema_with_answers = run_stage_2(args.sa, schema)
        else:
            swa_path = os.path.join(PIPELINE_OUTPUT, "schema_with_answers.json")
            with open(swa_path, "r") as f:
                schema_with_answers = json.load(f)
            print(f"[SKIP] Stage 2 — loaded schema_with_answers from {swa_path}")

        # STAGE 3
        if args.skip_to <= 3:
            ocr_text = run_stage_3(args.as_pdf)
        else:
            ocr_path = os.path.join(PIPELINE_TEMP, "3_ocr_output.txt")
            with open(ocr_path, "r") as f:
                ocr_text = f.read()
            print(f"[SKIP] Stage 3 — loaded OCR from {ocr_path}")

        # STAGE 4
        if args.skip_to <= 4:
            aligned = run_stage_4(schema_with_answers, ocr_text)
        else:
            aligned_path = os.path.join(PIPELINE_OUTPUT, "aligned_answers.json")
            with open(aligned_path, "r") as f:
                aligned = json.load(f)
            print(f"[SKIP] Stage 4 — loaded aligned from {aligned_path}")

        # STAGE 5
        if args.skip_to <= 5:
            grading_results = run_stage_5(aligned)
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
        if os.path.exists(grading_src):
            shutil.copy2(grading_src, os.path.join(dataset_dir, "grading_final.json"))

        # STAGE 6
        run_stage_6(dataset_dir)

        # STAGE 7
        run_stage_7(as_path=args.as_pdf, dataset_dir=dataset_dir)

        elapsed = time.time() - start_time
        print("\n" + "=" * 60)
        print(f"  ✓ PIPELINE COMPLETE in {elapsed:.1f}s")
        print(f"  Results: {dataset_dir}/")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ PIPELINE FAILED: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
