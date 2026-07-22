#!/usr/bin/env python3
"""
CA Specialized Stage 1 & 2 Combined:
Step 1 — Extracts question schema (questions only, no answers).
Step 2 — Populates model answers into that schema from the same PDF.
"""
import os
import sys
import json
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

def main():
    parser = argparse.ArgumentParser(description='Extract CA schema and model answers (two-step)')
    parser.add_argument('--sa', required=True, help='Path to Solution Answer PDF')
    parser.add_argument('--dataset', required=True, help='Dataset ID')

    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    dataset_dir = os.path.join(base_dir, "feedback_results", f"dataset_{args.dataset}")
    os.makedirs(dataset_dir, exist_ok=True)

    print("="*60)
    print("CA STAGE 1 & 2 Combined: Two-Step Schema & Model Answer Extraction")
    print("="*60)
    print(f"Solution PDF: {args.sa}")
    print(f"Dataset: {args.dataset}")

    # ── Step 1: Extract question structure only ────────────────────────
    print("\n[Step 1] Extracting question schema (no answers)...")
    solution_text = extract_solution_text_robust(args.sa)
    question_schema = build_questions_schema(solution_text)

    questions_path = os.path.join(dataset_dir, "question_schema.json")
    with open(questions_path, "w") as f:
        json.dump(question_schema, f, indent=2, ensure_ascii=False)
    print(f"✓ Question schema saved to: {questions_path}")

    # Count questions found
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

    # ── Step 2: Populate model answers into the schema ─────────────────
    print("\n[Step 2] Populating model answers into question schema...")
    schema_with_answers = build_model_answers_claude(
        question_schema=question_schema,
        solution_text=solution_text,
        pdf_path=args.sa,
    )

    # ── Save final combined schema ──────────────────────────────────────
    output_path = os.path.join(dataset_dir, "schema_with_answers.json")
    with open(output_path, "w") as f:
        json.dump(schema_with_answers, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Schema with answers saved to: {output_path}")
    print("Done. Next: run_ca_ocr_3.py")

if __name__ == "__main__":
    main()
