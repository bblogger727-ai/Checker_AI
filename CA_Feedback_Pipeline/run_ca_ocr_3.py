#!/usr/bin/env python3
"""
CA Specialized Stage 3:
OCRs student answer sheet page range options:
  - Default: pages 3 to (total_pages - 1), extracts marks from last page.
  - --last-page N: OCR pages 3 to N only (no last-page mark extraction).
  - --marks-mode json: copies student_marks.json from project root into dataset.
  - --marks-mode auto (default): parses marks from the last page via Claude.
"""
import os
import sys
import json
import shutil
import argparse
import fitz
from PIL import Image

pipeline_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(pipeline_dir, "..", "CheckerAI - Backend")
sys.path.insert(0, backend_dir)
from dotenv import load_dotenv
load_dotenv(os.path.join(backend_dir, ".env"))

from app.services.ocr_service import perform_ocr
from app.services.ca_mark_parser import parse_student_marks

def main():
    parser = argparse.ArgumentParser(description='CA Specialized OCR & Mark Extraction')
    parser.add_argument('--as', dest='as_pdf', required=True, help='Path to Student Answer PDF')
    parser.add_argument('--dataset', required=True, help='Dataset ID')
    parser.add_argument(
        '--marks-mode',
        dest='marks_mode',
        choices=['auto', 'json'],
        default='auto',
        help=(
            'How to get student marks. '
            '"auto" (default) = extract from last page of answer sheet. '
            '"json" = read student_marks.json from project root (no last-page parse).'
        )
    )
    parser.add_argument(
        '--last-page',
        dest='last_page',
        type=int,
        default=None,
        help=(
            'Last page number to OCR (inclusive, 1-indexed). '
            'When given, OCR covers pages 3 to this page only. '
            'Defaults to (total_pages - 1) when --marks-mode auto, '
            'or total_pages when --marks-mode json.'
        )
    )

    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    dataset_dir = os.path.join(base_dir, "feedback_results", f"dataset_{args.dataset}")
    os.makedirs(dataset_dir, exist_ok=True)

    print("="*60)
    print("CA STAGE 3: Specialized OCR & Mark Extraction")
    print("="*60)
    print(f"Student PDF:  {args.as_pdf}")
    print(f"Dataset:      {args.dataset}")
    print(f"Marks mode:   {args.marks_mode}")
    print(f"Last page:    {args.last_page if args.last_page else 'auto'}")

    doc = fitz.open(args.as_pdf)
    total_pages = len(doc)
    print(f"Total pages in PDF: {total_pages}")

    marks_path = os.path.join(dataset_dir, "student_marks.json")

    # ── Mark extraction ────────────────────────────────────────────────
    if args.marks_mode == 'json':
        # Copy student_marks.json from project root to dataset dir
        # Script is in CheckerAI - Backend/, user file is in CheckerAI/
        src_marks = os.path.join(base_dir, "..", "student_marks.json")
        if not os.path.exists(src_marks):
            # Try same directory as fallback
            src_marks = os.path.join(base_dir, "student_marks.json")
            
        if not os.path.exists(src_marks):
            print(f"Error: student_marks.json not found at {src_marks}")
            sys.exit(1)
        shutil.copy(src_marks, marks_path)
        print(f"\n[Marks] Copied {src_marks} → {marks_path}")

    else:  # auto
        # Determine last page for mark extraction
        mark_page_idx = total_pages - 1  # 0-indexed last page
        print(f"\n[Marks] Extracting marks from last page (Page {total_pages})...")
        last_page = doc[mark_page_idx]
        last_page_text = last_page.get_text()
        print("Parsing marks text using Claude...")
        marks_data = parse_student_marks(last_page_text)
        with open(marks_path, "w") as f:
            json.dump(marks_data, f, indent=2, ensure_ascii=False)
        print(f"✓ Student marks saved to: {marks_path}")

    # ── Determine OCR page range ───────────────────────────────────────
    # Pages are 0-indexed internally; page numbers shown to user are 1-indexed.
    ocr_start = 2  # Page 3 (0-indexed = 2)

    if args.last_page is not None:
        # User-specified last page (1-indexed), inclusive
        ocr_end = args.last_page  # We'll range(ocr_start, ocr_end) so this is exclusive
        if args.last_page > total_pages:
            print(f"Warning: --last-page {args.last_page} exceeds total pages {total_pages}. Clamping.")
            ocr_end = total_pages
        print(f"\n[OCR] Will OCR pages 3 to {args.last_page} (user-specified).")
    elif args.marks_mode == 'json':
        # No last-page skipping needed; OCR all content pages
        ocr_end = total_pages
        print(f"\n[OCR] Marks from JSON — will OCR pages 3 to {total_pages}.")
    else:
        # auto mode: skip last page (it was used for marks)
        ocr_end = total_pages - 1
        print(f"\n[OCR] Will OCR pages 3 to {total_pages - 1} (last page reserved for marks).")

    # ── Perform OCR ────────────────────────────────────────────────────
    ocr_path = os.path.join(dataset_dir, "ocr_output.txt")
    if os.path.exists(ocr_path):
        print(f"\n[OCR] OCR output already exists at {ocr_path}. Skipping OCR to save costs.")
    else:
        all_ocr_text = ""
        pages_to_ocr = list(range(ocr_start, ocr_end))
        print(f"\n[OCR] Performing OCR on {len(pages_to_ocr)} page(s)...")
        for page_num in pages_to_ocr:
            print(f"  Processing page {page_num + 1}/{total_pages}...", flush=True)
            page = doc[page_num]
            pix = page.get_pixmap(dpi=200)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            page_text = perform_ocr(img)
            all_ocr_text += f"\n=== Page {page_num + 1} ===\n```\n{page_text}\n```\n"

        with open(ocr_path, "w") as f:
            f.write(all_ocr_text)
        print(f"\n✓ OCR output saved to: {ocr_path}")

    doc.close()
    print("\nDone. Next: run_ca_alignment_4.py")

if __name__ == "__main__":
    main()
