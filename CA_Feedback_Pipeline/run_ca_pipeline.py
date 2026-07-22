#!/usr/bin/env python3
"""
Specialized CA Feedback Pipeline

Supports two modes:
  --mode full   (default) Full paper pipeline: Stages 1-6
  --mode single           Single-question image pipeline (no full paper PDFs needed)

Full paper usage:
  python3 run_ca_pipeline.py --mode full --sa solution.pdf --as student.pdf --dataset MY_DATASET

Single question usage:
  python3 run_ca_pipeline.py --mode single \
      --question-image question.jpg \
      --model-answer-image model_answer.jpg \
      --student-answer-image student_answer.jpg \
      --marks-total 6 --marks-scored 4 \
      --dataset MY_DATASET
"""
import os
import subprocess
import argparse
import sys

def run_step(command):
    print(f"\n>>> Running: {' '.join(command)}")
    result = subprocess.run(command)
    if result.returncode != 0:
        print(f"!!! Error running step: {command[0]}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description='CA Specialized Feedback Pipeline')
    parser.add_argument('--mode', choices=['full', 'single'], default='full',
                        help='Pipeline mode: "full" for full paper, "single" for single question images')

    # Full paper args
    parser.add_argument('--sa', help='[full] Path to Solution Answer PDF')
    parser.add_argument('--as', dest='as_pdf', help='[full] Path to Student Answer PDF')

    # Single question args
    parser.add_argument('--question-image', help='[single] Path to question image')
    parser.add_argument('--model-answer-image', help='[single] Path to model answer image')
    parser.add_argument('--student-answer-image', help='[single] Path to student answer image')
    parser.add_argument('--marks-total', type=float, help='[single] Total marks for this question')
    parser.add_argument('--marks-scored', type=float, help='[single] Marks scored by student')

    # Shared
    parser.add_argument('--dataset', required=True, help='Dataset ID')
    parser.add_argument('--last-page', type=int, help='Last page to OCR (1-indexed)')
    parser.add_argument('--marks-mode', choices=['auto', 'json'], default='auto', help='Marks extraction mode')

    args = parser.parse_args()

    if args.mode == 'single':
        # Validate required single-question args
        missing = []
        for field in ['question_image', 'model_answer_image', 'student_answer_image', 'marks_total', 'marks_scored']:
            if getattr(args, field) is None:
                missing.append(f'--{field.replace("_", "-")}')
        if missing:
            print(f"Error: Missing required arguments for --mode single: {', '.join(missing)}")
            sys.exit(1)

        print("=" * 60)
        print("STARTING CA SINGLE-QUESTION FEEDBACK PIPELINE")
        print("=" * 60)
        run_step([
            sys.executable, "run_ca_single_question.py",
            "--question-image", args.question_image,
            "--model-answer-image", args.model_answer_image,
            "--student-answer-image", args.student_answer_image,
            "--marks-total", str(args.marks_total),
            "--marks-scored", str(args.marks_scored),
            "--dataset", args.dataset,
        ])

    else:
        # Full paper mode
        if not args.sa or not args.as_pdf:
            print("Error: --sa and --as are required for --mode full")
            sys.exit(1)

        print("=" * 60)
        print("STARTING SPECIALIZED CA FEEDBACK PIPELINE")
        print("=" * 60)

        run_step([sys.executable, "run_ca_combined_1_2.py", "--sa", args.sa, "--dataset", args.dataset])
        
        ocr_cmd = [sys.executable, "run_ca_ocr_3.py", "--as", args.as_pdf, "--dataset", args.dataset, "--marks-mode", args.marks_mode]
        if args.last_page:
            ocr_cmd.extend(["--last-page", str(args.last_page)])
        run_step(ocr_cmd)
        
        run_step([sys.executable, "run_ca_alignment_4.py", "--dataset", args.dataset])
        run_step([sys.executable, "run_ca_feedback_5.py", "--dataset", args.dataset])
        run_step([sys.executable, "run_ca_report_6.py", "--dataset", args.dataset])
        run_step([sys.executable, "run_ca_pdf_report_7.py", "--dataset", args.dataset])

    print("\n" + "=" * 60)
    print("CA FEEDBACK PIPELINE COMPLETED SUCCESSFULLY")
    print("=" * 60)
    print(f"Final report in: feedback_results/dataset_{args.dataset}/")

if __name__ == "__main__":
    # Ensure subprocesses run from the script's directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    main()
