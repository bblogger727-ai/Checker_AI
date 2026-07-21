#!/usr/bin/env python3
"""
Stage 5: Grading (Claude Version)
Grades student answers using Claude Sonnet 4 two-phase system.
Requires: aligned_answers.json
"""
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

from claude_grading.answer_grader_claude import grade_all_answers


def main():
    parser = argparse.ArgumentParser(description='Grade student answers using Claude')
    parser.add_argument('--aligned', default=None, help='Path to aligned_answers.json')
    parser.add_argument('--dataset', default=None, help='Dataset name (optional)')
    
    args = parser.parse_args()
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    if args.dataset:
        dataset_dir = os.path.join(base_dir, "grading_results", f"dataset_{args.dataset}")
        aligned_path = args.aligned or os.path.join(dataset_dir, "aligned_answers.json")
        output_path = os.path.join(dataset_dir, "grading_final.json")
    else:
        output_dir = os.path.join(os.path.dirname(base_dir), "pipeline_output")
        results_dir = os.path.join(base_dir, "grading_results")
        aligned_path = args.aligned or os.path.join(output_dir, "aligned_answers.json")
        output_path = os.path.join(results_dir, "grading_final.json")
    
    # Load aligned answers
    if not os.path.exists(aligned_path):
        print(f"Error: Aligned answers not found at {aligned_path}")
        sys.exit(1)
    
    with open(aligned_path, "r") as f:
        aligned = json.load(f)
    
    print("="*60)
    print("STAGE 5: Grading (Claude Two-Phase)")
    print("="*60)
    print(f"Aligned answers: {aligned_path}")
    
    # Grade
    print("Grading answers using Claude (this may take a few minutes)...")
    grading_results = grade_all_answers(
        aligned_answers=aligned,
        model_answers=aligned  # Schema already merged with model answers
    )
    
    # Save
    with open(output_path, "w") as f:
        json.dump(grading_results, f, indent=2, ensure_ascii=False)
    
    print(f"✓ Grading results saved to: {output_path}")
    
    # Print summary
    if 'metadata' in grading_results:
        meta = grading_results['metadata']
        print(f"\n  Score: {meta.get('total_marks_obtained', 0)}/{meta.get('total_marks_possible', 0)}")
        print(f"  Percentage: {meta.get('percentage', 0):.2f}%")
        print(f"  Grade: {meta.get('grade', 'N/A')}")
    
    print("\nDone. Next: run_stage_6_report.py")


if __name__ == "__main__":
    main()
