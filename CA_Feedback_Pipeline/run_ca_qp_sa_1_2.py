#!/usr/bin/env python3
"""
CA Specialized Stage 1 & 2 — Split Input Mode:
  Step 1 — Extract question structure ONLY from the Question Paper PDF using Tesseract OCR.
  Step 2 — Extract model answers from the Suggested Solution PDF using normal text extraction
            (fitz direct), then align answers to the question schema.

Usage:
  python3 run_ca_qp_sa_1_2.py --qp question_paper.pdf --sa solution.pdf --dataset MY_DATASET
"""
import os
import sys
import json
import subprocess
import tempfile
import argparse
import fitz

pipeline_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(pipeline_dir, "..", "CheckerAI - Backend")
sys.path.insert(0, backend_dir)
from dotenv import load_dotenv
load_dotenv(os.path.join(backend_dir, ".env"))

from app.services.ca_schema_builder import build_questions_schema
from claude_grading.model_answer_builder_claude import (
    extract_solution_text_robust,
    build_model_answers_claude,
)


def extract_pdf_text_tesseract_qp(pdf_path: str) -> str:
    """
    Extract text from a Question Paper PDF using Tesseract OCR page by page.
    Always uses OCR regardless of whether the PDF has embedded text.
    Returns full text with ========== PAGE N ========== markers.
    """
    print(f"[QP Tesseract OCR] Extracting text from: {pdf_path}", flush=True)
    doc = fitz.open(pdf_path)
    all_text = []

    with tempfile.TemporaryDirectory() as tmpdir:
        for i, page in enumerate(doc):
            page_num = i + 1
            # Use 2x scale for good OCR quality
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat)
            img_path = os.path.join(tmpdir, f"page_{page_num}.png")
            pix.save(img_path)
            print(f"  [QP OCR] Processing page {page_num}/{len(doc)}...", flush=True)
            try:
                result = subprocess.run(
                    ["tesseract", img_path, "stdout", "-l", "eng", "--psm", "6"],
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                text = result.stdout
                all_text.append(f"========== PAGE {page_num} ==========\n{text}\n")
            except subprocess.TimeoutExpired:
                print(f"  [QP OCR] Warning: Tesseract timed out on page {page_num}. Skipping.")
            except Exception as e:
                print(f"  [QP OCR] Warning: Tesseract failed on page {page_num}: {e}")

    doc.close()
    print(f"[QP Tesseract OCR] Extracted {len(all_text)} pages.", flush=True)
    return "\n".join(all_text)


def extract_solution_text_direct(pdf_path: str) -> str:
    """
    Extract text from the Suggested Solution PDF using fitz direct text extraction.
    This is for a digitally-generated (non-scanned) solution PDF.
    Returns full text with ========== PAGE N ========== markers.
    """
    print(f"[Solution Text Extraction] Extracting text from: {pdf_path}", flush=True)
    doc = fitz.open(pdf_path)
    all_text = []
    total_chars = 0
    for i, page in enumerate(doc):
        text = page.get_text()
        total_chars += len(text.strip())
        all_text.append(f"========== PAGE {i+1} ==========\n{text}\n")
    avg_chars = total_chars / len(doc) if len(doc) > 0 else 0
    print(f"[Solution Text Extraction] Done. Avg chars/page: {avg_chars:.1f}", flush=True)
    if avg_chars < 50:
        print("[Solution Text Extraction] WARNING: Very sparse text — the solution PDF may be scanned. Consider using robust extraction.", flush=True)
    doc.close()
    return "\n".join(all_text)


def main():
    parser = argparse.ArgumentParser(
        description='CA Stage 1+2: Tesseract OCR on QP + Direct text from Solution, then align answers.'
    )
    parser.add_argument('--qp', required=True, help='Path to Question Paper PDF (will use Tesseract OCR)')
    parser.add_argument('--sa', required=True, help='Path to Suggested Solution Answer PDF (will use direct text extraction)')
    parser.add_argument('--dataset', required=True, help='Dataset ID')
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    dataset_dir = os.path.join(base_dir, "feedback_results", f"dataset_{args.dataset}")
    os.makedirs(dataset_dir, exist_ok=True)

    print("=" * 60)
    print("CA STAGE 1 & 2 (Split QP+SA Mode): Tesseract QP → Schema → Solution Answers")
    print("=" * 60)
    print(f"Question Paper PDF : {args.qp}")
    print(f"Solution Answer PDF: {args.sa}")
    print(f"Dataset            : {args.dataset}")

    # ── Step 1: Extract question text from QP using Tesseract OCR ─────────────
    print("\n[Step 1] Extracting question paper text using Tesseract OCR...")
    qp_text = extract_pdf_text_tesseract_qp(args.qp)

    # Save raw QP OCR output for inspection / debugging
    qp_ocr_path = os.path.join(dataset_dir, "qp_ocr_text.txt")
    with open(qp_ocr_path, "w") as f:
        f.write(qp_text)
    print(f"  → QP OCR text saved to: {qp_ocr_path}")

    # ── Step 1b: Build question schema (structure only, no answers) ────────────
    print("\n[Step 1b] Building question schema from OCR text (Claude)...")
    question_schema = build_questions_schema(qp_text)

    questions_path = os.path.join(dataset_dir, "question_schema.json")
    with open(questions_path, "w") as f:
        json.dump(question_schema, f, indent=2, ensure_ascii=False)
    print(f"  → Question schema saved to: {questions_path}")

    def _count_questions(node, count=0):
        if isinstance(node, dict):
            if "question_id" in node:
                count += 1
            for v in node.values():
                count = _count_questions(v, count)
        elif isinstance(node, list):
            for i in node:
                count = _count_questions(i, count)
        return count

    q_count = _count_questions(question_schema)
    print(f"  → Found {q_count} descriptive questions in schema.")

    # ── Step 2: Extract solution text using direct (fitz) text extraction ──────
    print("\n[Step 2] Extracting model solution text (direct text extraction)...")
    solution_text = extract_solution_text_direct(args.sa)

    # Save raw solution text for inspection
    sol_text_path = os.path.join(dataset_dir, "solution_text.txt")
    with open(sol_text_path, "w") as f:
        f.write(solution_text)
    print(f"  → Solution text saved to: {sol_text_path}")

    # ── Step 2b: Align model answers from solution PDF into the question schema ─
    print("\n[Step 2b] Aligning model answers from solution into question schema (Claude)...")
    schema_with_answers = build_model_answers_claude(
        question_schema=question_schema,
        solution_text=solution_text,
        pdf_path=args.sa,
    )

    output_path = os.path.join(dataset_dir, "schema_with_answers.json")
    with open(output_path, "w") as f:
        json.dump(schema_with_answers, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Schema with answers saved to: {output_path}")
    print("Done. Next: run_ca_ocr_3.py")


if __name__ == "__main__":
    main()
