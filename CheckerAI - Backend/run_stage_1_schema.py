#!/usr/bin/env python3
"""
Stage 1: Schema Generation
Generates question schema from Question Paper PDF.
Can be reused if QP hasn't changed.
"""
import os
import sys
import json
import argparse
import fitz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

from app.services.solution_schema_builder import build_solution_schema


def extract_pdf_text(pdf_path: str) -> str:
    """Extract all text from PDF using PyMuPDF."""
    doc = fitz.open(pdf_path)
    text = ""
    for page_num, page in enumerate(doc, 1):
        page_text = page.get_text()
        text += f"\n\n=== Page {page_num} ===\n{page_text}"
    doc.close()
    return text


def main():
    parser = argparse.ArgumentParser(description='Generate question schema from Question Paper')
    parser.add_argument('--qp', required=True, help='Path to Question Paper PDF')
    parser.add_argument('--output', default='../pipeline_output', help='Output directory')
    
    args = parser.parse_args()
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(os.path.dirname(base_dir), "pipeline_output")
    temp_dir = os.path.join(base_dir, "pipeline_temp")
    
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(temp_dir, exist_ok=True)
    
    print("="*60)
    print("STAGE 1: Schema Generation")
    print("="*60)
    print(f"Question Paper: {args.qp}")
    
    # Extract QP text
    print("Extracting text from QP...")
    qp_text = extract_pdf_text(args.qp)
    
    # Save for debugging
    qp_text_path = os.path.join(temp_dir, "1_qp_text.txt")
    with open(qp_text_path, "w") as f:
        f.write(qp_text)
    print(f"✓ Saved QP text to: {qp_text_path}")
    
    # Build schema
    print("Building schema...")
    schema = build_solution_schema(qp_text)
    
    # Save schema
    schema_path = os.path.join(output_dir, "schema.json")
    with open(schema_path, "w") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
    
    print(f"✓ Schema saved to: {schema_path}")
    print("\nDone. Next: run_stage_2_model_answers.py")


if __name__ == "__main__":
    main()
