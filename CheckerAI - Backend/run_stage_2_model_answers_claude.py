#!/usr/bin/env python3
"""
Stage 2 (Claude): Model Answer Extraction
Extracts model answers from Solution PDF and merges with schema using Claude.
Requires: schema.json from Stage 1
"""
import os
import sys
import json
import argparse
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

from claude_grading.model_answer_builder_claude import build_model_answers_claude
from app.services.model_answer_builder import extract_pdf_text_tesseract


def main():
    parser = argparse.ArgumentParser(description='Extract model answers from Solution PDF (Claude)')
    parser.add_argument('--sa', required=True, help='Path to Solution Answer PDF')
    parser.add_argument('--schema', required=True, help='Path to schema.json')
    parser.add_argument('--dataset', required=True, help='Dataset ID')
    
    args = parser.parse_args()
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dataset_dir = os.path.join(base_dir, "grading_results", f"dataset_{args.dataset}")
    temp_dir = os.path.join(base_dir, "pipeline_temp")
    
    os.makedirs(dataset_dir, exist_ok=True)
    os.makedirs(temp_dir, exist_ok=True)
    
    # Load schema
    if not os.path.exists(args.schema):
        print(f"Error: Schema not found at {args.schema}")
        sys.exit(1)
    
    with open(args.schema, "r") as f:
        schema = json.load(f)
    
    print("="*60)
    print("STAGE 2 (Claude): Model Answer Extraction")
    print("="*60)
    print(f"Solution PDF: {args.sa}")
    print(f"Schema: {args.schema}")
    print(f"Dataset: {args.dataset}")
    
    # Build model answers using robust extraction
    print("Extracting model answers with Claude + OpenAI Vision (Robust Mode)...")
    schema_with_answers = build_model_answers_claude(schema, pdf_path=args.sa)
    
    # Save complete schema to dataset directory
    complete_path = os.path.join(dataset_dir, "schema_with_answers.json")
    with open(complete_path, "w") as f:
        json.dump(schema_with_answers, f, indent=2, ensure_ascii=False)
    
    print(f"✓ Schema with answers saved to: {complete_path}")
    print("\nDone. Next: Verify the extracted model answers in schema_with_answers.json")


if __name__ == "__main__":
    main()
