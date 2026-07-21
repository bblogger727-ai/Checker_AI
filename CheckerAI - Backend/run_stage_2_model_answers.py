#!/usr/bin/env python3
"""
Stage 2: Model Answer Extraction
Extracts model answers from Solution PDF and merges with schema.
Requires: schema.json from Stage 1
"""
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

from app.services.model_answer_builder import build_model_answers, extract_pdf_text_tesseract


def main():
    parser = argparse.ArgumentParser(description='Extract model answers from Solution PDF')
    parser.add_argument('--sa', required=True, help='Path to Solution Answer PDF')
    parser.add_argument('--schema', default=None, help='Path to schema.json (default: auto-detect)')
    
    args = parser.parse_args()
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(os.path.dirname(base_dir), "pipeline_output")
    temp_dir = os.path.join(base_dir, "pipeline_temp")
    
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(temp_dir, exist_ok=True)
    
    # Load schema
    schema_path = args.schema or os.path.join(output_dir, "schema.json")
    if not os.path.exists(schema_path):
        print(f"Error: Schema not found at {schema_path}")
        print("Run stage 1 first: python run_stage_1_schema.py --qp QP.pdf")
        sys.exit(1)
    
    with open(schema_path, "r") as f:
        schema = json.load(f)
    
    print("="*60)
    print("STAGE 2: Model Answer Extraction")
    print("="*60)
    print(f"Solution PDF: {args.sa}")
    print(f"Schema: {schema_path}")
    
    # Extract SA text with Tesseract
    print("Extracting text from SA (Tesseract OCR for tables)...")
    sa_text = extract_pdf_text_tesseract(args.sa)
    
    # Save for debugging
    sa_text_path = os.path.join(temp_dir, "2_sa_text.txt")
    with open(sa_text_path, "w") as f:
        f.write(sa_text)
    print(f"✓ Saved SA text to: {sa_text_path}")
    
    # Build model answers (pass pdf_path to enable vision strategies)
    print("Extracting model answers...")
    schema_with_answers = build_model_answers(schema, sa_text, pdf_path=args.sa)
    
    # Save complete schema to pipeline_output
    complete_path = os.path.join(output_dir, "schema_with_answers.json")
    with open(complete_path, "w") as f:
        json.dump(schema_with_answers, f, indent=2, ensure_ascii=False)
    print(f"✓ Schema with answers saved to: {complete_path}")

    # Also sync to any existing grading_results/dataset_*/ directories
    import glob, shutil
    grading_base = os.path.join(base_dir, "grading_results")
    dataset_dirs = glob.glob(os.path.join(grading_base, "dataset_*"))
    for dataset_dir in sorted(dataset_dirs):
        dest = os.path.join(dataset_dir, "schema_with_answers.json")
        shutil.copy2(complete_path, dest)
        print(f"✓ Synced to: {dest}")
    print("\nDone. Next: run_stage_3_ocr.py")


if __name__ == "__main__":
    main()
