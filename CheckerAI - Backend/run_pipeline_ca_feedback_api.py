#!/usr/bin/env python3
"""
CA Feedback Pipeline Runner — API Edition
=============================================
Wrapper around CA_Feedback_Pipeline scripts to work as a subprocess called by
the CheckerAI FastAPI backend.

Key features:
  --output-dir  Required. The backend job directory where result.json is updated.
  --sa, --as    Paths to Solution and Answer Sheet PDFs.
  --marks-json  Stringified JSON of the marks provided by the UI.

This script executes the CA_Feedback_Pipeline steps as subprocesses, translating
the hardcoded output folder into the API's standard output_dir and tracking progress.
"""
import os
import sys
import json
import argparse
import time
import shutil
import subprocess

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
PIPELINE_DIR = os.path.join(os.path.dirname(BASE_DIR), "CA_Feedback_Pipeline")

def update_status(output_dir: str, status_data: dict):
    res_path = os.path.join(output_dir, "result.json")
    with open(res_path, "w", encoding="utf-8") as f:
        json.dump(status_data, f, indent=2)
    print(f"[STATUS UPDATE] {status_data.get('stage')} - {status_data.get('message')}")

def run_step(command, cwd):
    print(f"\n>>> Running: {' '.join(command)}")
    result = subprocess.run(command, cwd=cwd)
    if result.returncode != 0:
        print(f"!!! Error running step: {command[0]}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description='CA Feedback Pipeline API Wrapper')
    parser.add_argument('--output-dir', required=True, help='API job directory for result.json')
    parser.add_argument('--sa', required=True, help='Solution PDF path')
    parser.add_argument('--as-pdf', required=True, help='Student Answer Sheet PDF path')
    parser.add_argument('--marks-json', required=True, help='Path to JSON file containing the user marks')
    parser.add_argument('--task-id', required=True, help='The task ID from the backend')
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    task_id = args.task_id

    # The CA pipeline hardcodes its output to CA_Feedback_Pipeline/feedback_results/dataset_{task_id}
    ca_dataset_dir = os.path.join(PIPELINE_DIR, "feedback_results", f"dataset_{task_id}")
    os.makedirs(ca_dataset_dir, exist_ok=True)

    # 1. Save the student marks to the ca_dataset_dir so run_ca_ocr_3.py can find it
    student_marks_dest = os.path.join(ca_dataset_dir, "student_marks.json")
    shutil.copy2(args.marks_json, student_marks_dest)

    try:
        # Initialize
        update_status(args.output_dir, {
            "status": "running",
            "stage": "started",
            "message": "Starting CA Feedback Pipeline...",
            "progress": 0
        })

        # Stages 1 & 2
        update_status(args.output_dir, {
            "status": "running",
            "stage": "stage_1_2",
            "message": "Extracting schema and model answers...",
            "progress": 15
        })
        run_step([sys.executable, "run_ca_combined_1_2.py", "--sa", args.sa, "--dataset", task_id], cwd=PIPELINE_DIR)

        # Stage 3 (OCR - skipping last page since marks are provided via JSON)
        update_status(args.output_dir, {
            "status": "running",
            "stage": "stage_3",
            "message": "Running OCR on student answers...",
            "progress": 30
        })
        run_step([sys.executable, "run_ca_ocr_3.py", "--as", args.as_pdf, "--dataset", task_id, "--marks-mode", "json"], cwd=PIPELINE_DIR)

        # Stage 4 (Alignment)
        update_status(args.output_dir, {
            "status": "running",
            "stage": "stage_4",
            "message": "Aligning OCR text with question schema...",
            "progress": 45
        })
        run_step([sys.executable, "run_ca_alignment_4.py", "--dataset", task_id], cwd=PIPELINE_DIR)

        # Stage 5 (Feedback Generation)
        update_status(args.output_dir, {
            "status": "running",
            "stage": "stage_5",
            "message": "Generating feedback with AI...",
            "progress": 60
        })
        run_step([sys.executable, "run_ca_feedback_5.py", "--dataset", task_id], cwd=PIPELINE_DIR)

        # Stage 6 (Report generation)
        update_status(args.output_dir, {
            "status": "running",
            "stage": "stage_6",
            "message": "Generating PDF grading report...",
            "progress": 80
        })
        run_step([sys.executable, "run_ca_report_6.py", "--dataset", task_id], cwd=PIPELINE_DIR)

        # Stage 7 (Checked Copy)
        update_status(args.output_dir, {
            "status": "running",
            "stage": "stage_7",
            "message": "Annotating checked copy...",
            "progress": 90
        })
        run_step([sys.executable, "run_ca_pdf_report_7.py", "--dataset", task_id], cwd=PIPELINE_DIR)

        # ── Collect outputs and move to output_dir ───────────────────────────
        
        # Read the grading json to get total marks, grade, etc
        grading_json_path = os.path.join(ca_dataset_dir, "grading_final.json")
        stats = {}
        if os.path.exists(grading_json_path):
            with open(grading_json_path, "r") as f:
                gdata = json.load(f)
                stats = {
                    "total_marks_obtained": gdata.get("metadata", {}).get("total_marks_obtained"),
                    "total_marks_possible": gdata.get("metadata", {}).get("total_marks_possible"),
                    "percentage": gdata.get("metadata", {}).get("percentage"),
                    "grade": gdata.get("metadata", {}).get("grade")
                }

        # Copy the final PDFs to output_dir so the API can serve them
        checked_copy_src = os.path.join(ca_dataset_dir, "checked_copy.pdf")
        if os.path.exists(checked_copy_src):
            shutil.copy2(checked_copy_src, os.path.join(args.output_dir, "checked_copy.pdf"))
            
        report_src = os.path.join(ca_dataset_dir, "grading_report.pdf")
        if os.path.exists(report_src):
            shutil.copy2(report_src, os.path.join(args.output_dir, "grading_report.pdf"))

        # Mark done
        update_status(args.output_dir, {
            "status": "done",
            "stage": "completed",
            "message": "Grading Complete!",
            "progress": 100,
            "checked_copy_ready": os.path.exists(checked_copy_src),
            "grading_report_ready": os.path.exists(report_src),
            **stats
        })

    except Exception as e:
        import traceback
        err_msg = str(e)
        print(traceback.format_exc())
        update_status(args.output_dir, {
            "status": "failed",
            "stage": "failed",
            "message": f"Pipeline failed: {err_msg}",
            "error": err_msg
        })
        sys.exit(1)

if __name__ == "__main__":
    main()
