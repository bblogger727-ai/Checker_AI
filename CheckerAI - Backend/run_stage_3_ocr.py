#!/usr/bin/env python3
"""
Stage 3: Student Answer OCR
OCRs student answer sheet and saves raw output.
"""
import os
import sys
import argparse
import fitz
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

from app.services.ocr_service import perform_ocr


def main():
    parser = argparse.ArgumentParser(description='OCR Student Answer Sheet')
    parser.add_argument('--as', dest='as_pdf', required=True, help='Path to Student Answer PDF')
    
    args = parser.parse_args()
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    temp_dir = os.path.join(base_dir, "pipeline_temp")
    os.makedirs(temp_dir, exist_ok=True)
    
    # Check if OCR already exists
    ocr_path = os.path.join(temp_dir, "3_ocr_output.txt")
    if os.path.exists(ocr_path):
        print(f"✓ OCR output already exists: {ocr_path}")
        print("Delete it to re-run OCR, or skip to stage 4.")
        sys.exit(0)
    
    print("="*60)
    print("STAGE 3: Student Answer OCR")
    print("="*60)
    print(f"Student PDF: {args.as_pdf}")
    
    # OCR each page
    doc = fitz.open(args.as_pdf)
    all_text = ""
    total_pages = len(doc)
    
    for page_num in range(total_pages):
        print(f"  Processing page {page_num + 1}/{total_pages}...", flush=True)
        page = doc[page_num]
        
        # Convert to image
        pix = page.get_pixmap(dpi=200)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        
        # OCR
        page_text = perform_ocr(img)
        all_text += f"\n=== Page {page_num + 1} ===\n```\n{page_text}\n```\n"
    
    doc.close()
    
    # Save OCR output
    with open(ocr_path, "w") as f:
        f.write(all_text)
    
    print(f"\n✓ OCR output saved to: {ocr_path}")
    print(f"  Total chars: {len(all_text)}")
    print("\nDone. Next: run_stage_4_alignment.py")


if __name__ == "__main__":
    main()
