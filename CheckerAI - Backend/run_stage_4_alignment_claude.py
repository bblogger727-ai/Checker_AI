#!/usr/bin/env python3
"""
Stage 4: Answer Alignment (Claude Version)
Aligns student answers to schema questions using Claude Sonnet 4.
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
from claude_grading.answer_aligner_claude import align_answers_to_schema_claude


def main():
    parser = argparse.ArgumentParser(description='Align student answers to schema using Claude')
    parser.add_argument('--schema', default=None, help='Path to schema_with_answers.json')
    parser.add_argument('--ocr', default=None, help='Path to OCR output txt')
    parser.add_argument('--dataset', default=None, help='Dataset name (optional)')
    
    args = parser.parse_args()
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    if args.dataset:
        dataset_dir = os.path.join(base_dir, "grading_results", f"dataset_{args.dataset}")
        schema_path = args.schema or os.path.join(dataset_dir, "schema_with_answers.json")
        ocr_path = args.ocr or os.path.join(dataset_dir, "ocr_output.txt")
        output_path = os.path.join(dataset_dir, "aligned_answers.json")
    else:
        output_dir = os.path.join(os.path.dirname(base_dir), "pipeline_output")
        temp_dir = os.path.join(base_dir, "pipeline_temp")
        schema_path = args.schema or os.path.join(output_dir, "schema_with_answers.json")
        ocr_path = args.ocr or os.path.join(temp_dir, "3_ocr_output.txt")
        output_path = os.path.join(output_dir, "aligned_answers.json")
    
    # Load schema
    if not os.path.exists(schema_path):
        print(f"Error: Schema not found at {schema_path}")
        sys.exit(1)
    
    with open(schema_path, "r") as f:
        schema = json.load(f)
    
    # Load OCR
    if not os.path.exists(ocr_path):
        print(f"Error: OCR output not found at {ocr_path}")
        sys.exit(1)
    
    with open(ocr_path, "r") as f:
        ocr_text = f.read()
    
    print("="*60)
    print("STAGE 4: Answer Alignment (Claude)")
    print("="*60)
    print(f"Schema: {schema_path}")
    print(f"OCR: {ocr_path}")
    
    # Parse OCR
    print("Parsing OCR text...")
    student_pages = parse_ocr_to_pages(ocr_text)
    print(f"Parsed {len(student_pages)} pages")
    
    # Align
    print("Aligning student answers to schema using Claude...")
    aligned = align_answers_to_schema_claude(student_pages, schema)
    
    # Save
    with open(output_path, "w") as f:
        json.dump(aligned, f, indent=2, ensure_ascii=False)
    
    print(f"✓ Aligned answers saved to: {output_path}")
    print("\nDone. Next: run_stage_5_grading.py")


if __name__ == "__main__":
    main()
