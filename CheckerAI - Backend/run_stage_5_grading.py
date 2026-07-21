#!/usr/bin/env python3
"""
Stage 5: Grading
Grades student answers against model answers using two-phase comparison system.
Requires: aligned_answers.json (text-based, no PDF needed for grading)
"""
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

from app.services.answer_grader import grade_all_answers


def main():
    parser = argparse.ArgumentParser(description='Grade student answers (two-phase system)')
    parser.add_argument('--aligned', default=None, help='Path to aligned_answers.json')
    
    args = parser.parse_args()
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(os.path.dirname(base_dir), "pipeline_output")
    results_dir = os.path.join(base_dir, "grading_results")
    
    os.makedirs(results_dir, exist_ok=True)
    
    # Load aligned answers
    aligned_path = args.aligned or os.path.join(output_dir, "aligned_answers.json")
    if not os.path.exists(aligned_path):
        print(f"Error: Aligned answers not found at {aligned_path}")
        print("Run stage 4 first: python run_stage_4_alignment.py")
        sys.exit(1)
    
    with open(aligned_path, "r") as f:
        aligned = json.load(f)
    
    print("="*60)
    print("STAGE 5: Grading (Two-Phase System)")
    print("="*60)
    print(f"Aligned answers: {aligned_path}")
    
    # Grade
    print("Grading answers (this may take a few minutes)...")
    grading_results = grade_all_answers(
        aligned_answers=aligned,
        model_answers=aligned  # Schema already merged with model answers
    )
    
    # Save
    grading_path = os.path.join(results_dir, "grading_final.json")
    with open(grading_path, "w") as f:
        json.dump(grading_results, f, indent=2, ensure_ascii=False)
    
    print(f"✓ Grading results saved to: {grading_path}")
    
    # Print summary
    if 'metadata' in grading_results:
        meta = grading_results['metadata']
        print(f"\n  Score: {meta.get('total_marks_obtained', 0)}/{meta.get('total_marks_possible', 0)}")
        print(f"  Percentage: {meta.get('percentage', 0):.2f}%")
        print(f"  Grade: {meta.get('grade', 'N/A')}")
    
    print("\nDone. Next: run_stage_6_report.py")


if __name__ == "__main__":
    main()
