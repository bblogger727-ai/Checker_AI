#!/usr/bin/env python3
"""
Stage 4: Answer Alignment
Aligns student answers to schema questions.
Requires: schema_with_answers.json, 3_ocr_output.txt
"""
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

from app.services.answer_parser import parse_ocr_to_pages
from app.services.answer_aligner import align_answers_to_schema


def main():
    parser = argparse.ArgumentParser(description='Align student answers to schema')
    parser.add_argument('--schema', default=None, help='Path to schema_with_answers.json')
    parser.add_argument('--ocr', default=None, help='Path to OCR output txt')
    
    args = parser.parse_args()
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(os.path.dirname(base_dir), "pipeline_output")
    temp_dir = os.path.join(base_dir, "pipeline_temp")
    
    # Load schema
    schema_path = args.schema or os.path.join(output_dir, "schema_with_answers.json")
    if not os.path.exists(schema_path):
        print(f"Error: Schema not found at {schema_path}")
        print("Run stage 2 first: python run_stage_2_model_answers.py --sa SA.pdf")
        sys.exit(1)
    
    with open(schema_path, "r") as f:
        schema = json.load(f)
    
    # Load OCR
    ocr_path = args.ocr or os.path.join(temp_dir, "3_ocr_output.txt")
    if not os.path.exists(ocr_path):
        print(f"Error: OCR output not found at {ocr_path}")
        print("Run stage 3 first: python run_stage_3_ocr.py --as AS.pdf")
        sys.exit(1)
    
    with open(ocr_path, "r") as f:
        ocr_text = f.read()
    
    print("="*60)
    print("STAGE 4: Answer Alignment")
    print("="*60)
    print(f"Schema: {schema_path}")
    print(f"OCR: {ocr_path}")
    
    # Parse OCR
    print("Parsing OCR text...")
    student_pages = parse_ocr_to_pages(ocr_text)
    print(f"Parsed {len(student_pages)} pages")
    
    # Align
    print("Aligning student answers to schema...")
    aligned = align_answers_to_schema(student_pages, schema)
    
    # Save
    aligned_path = os.path.join(output_dir, "aligned_answers.json")
    with open(aligned_path, "w") as f:
        json.dump(aligned, f, indent=2, ensure_ascii=False)
    
    print(f"✓ Aligned answers saved to: {aligned_path}")
    print("\nDone. Next: run_stage_5_grading.py")


if __name__ == "__main__":
    main()
