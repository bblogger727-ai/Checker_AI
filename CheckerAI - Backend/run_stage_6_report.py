#!/usr/bin/env python3
"""
Stage 6: Report Generation
Generates PDF report from grading results.
Requires: grading_final.json
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generate_grading_pdf import generate_pdf


def main():
    parser = argparse.ArgumentParser(description='Generate PDF grading report')
    parser.add_argument('--grading', default=None, help='Path to grading_final.json')
    parser.add_argument('--dataset', default=None, help='Dataset name (optional)')
    
    args = parser.parse_args()
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    if args.dataset:
        dataset_dir = os.path.join(base_dir, "grading_results", f"dataset_{args.dataset}")
        grading_path = args.grading or os.path.join(dataset_dir, "grading_final.json")
        report_path = os.path.join(dataset_dir, "grading_report.pdf")
    else:
        results_dir = os.path.join(base_dir, "grading_results")
        grading_path = args.grading or os.path.join(results_dir, "grading_final.json")
        report_path = os.path.join(results_dir, "grading_report.pdf")

    # Load grading results
    if not os.path.exists(grading_path):
        print(f"Error: Grading results not found at {grading_path}")
        sys.exit(1)
    
    print("="*60)
    print("STAGE 6: Report Generation")
    print("="*60)
    print(f"Grading results: {grading_path}")
    
    # Generate report
    generate_pdf(json_path=grading_path, output_path=report_path)
    
    print(f"✓ Report saved to: {report_path}")
    print("\n✓ Pipeline complete!")


if __name__ == "__main__":
    main()
