#!/usr/bin/env python3
"""
re_extract_wrong_lines.py
=========================
Lightweight script that re-runs only Phase 1 of Claude grading for an
existing dataset to populate the `wrong_lines` and `correct_lines` fields
in grading_final.json.

Does NOT change marks, tier, or any other grading data.

Usage:
    python3 re_extract_wrong_lines.py dataset_16064
    python3 re_extract_wrong_lines.py  # prompts for dataset name
"""

import os
import sys
import json
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from claude_grading.answer_grader_claude import _phase1_compare, is_practical_question


def flatten_graded_items(data, path=""):
    """
    Recursively yield (path, leaf_dict) for every graded item
    (every dict with 'marks_obtained' and 'student_answer').
    """
    if isinstance(data, dict):
        if "marks_obtained" in data and "student_answer" in data:
            yield path, data
        else:
            for key, val in data.items():
                child_path = f"{path}.{key}" if path else key
                yield from flatten_graded_items(val, child_path)


def re_extract(dataset_dir: str):
    grading_path = os.path.join(dataset_dir, "grading_final.json")
    if not os.path.exists(grading_path):
        print(f"[ERROR] grading_final.json not found at {grading_path}")
        return

    with open(grading_path, "r") as f:
        grading_data = json.load(f)

    graded_answers = grading_data.get("graded_answers", {})
    updated = 0
    skipped = 0

    for path, item in flatten_graded_items(graded_answers):
        q_text      = item.get("question_text") or item.get("question", "")
        student_ans = item.get("student_answer", "")
        model_ans   = item.get("model_answer", "")
        method      = item.get("grading_method", "")

        # Skip unanswered, skipped, or MCQ questions
        if method in ("no_answer", "skipped_or_alternative") or not student_ans.strip():
            skipped += 1
            continue
        if item.get("skipped_mcq") or item.get("skipped_or_alternative"):
            skipped += 1
            continue

        is_practical = is_practical_question(q_text)
        print(f"  -> Re-extracting Phase 1 for path={path} ({'practical' if is_practical else 'theory'})")

        try:
            comparison = _phase1_compare(q_text, model_ans, student_ans, is_practical)
            wrong_lines   = comparison.get("wrong_lines",   []) or []
            correct_lines = comparison.get("correct_lines", []) or []

            item["wrong_lines"]   = wrong_lines
            item["correct_lines"] = correct_lines

            print(f"     OK wrong_lines={wrong_lines[:3]}  correct_lines={correct_lines[:3]}")
            updated += 1

        except Exception as e:
            print(f"     ERROR: {e}")
            item.setdefault("wrong_lines", [])
            item.setdefault("correct_lines", [])

    # Write back
    with open(grading_path, "w") as f:
        json.dump(grading_data, f, indent=2)

    print(f"\n  Done. Updated {updated} questions, skipped {skipped}.")
    print(f"  Saved to {grading_path}")


def main():
    parser = argparse.ArgumentParser(description="Re-extract wrong_lines/correct_lines for a graded dataset")
    parser.add_argument("dataset", nargs="?", help="Dataset folder name (e.g. dataset_16064)")
    args = parser.parse_args()

    dataset_name = args.dataset
    if not dataset_name:
        dataset_name = input("Enter dataset folder name (e.g. dataset_16064): ").strip()

    dataset_dir = os.path.join(SCRIPT_DIR, "grading_results", dataset_name)
    if not os.path.isdir(dataset_dir):
        print(f"[ERROR] Directory not found: {dataset_dir}")
        sys.exit(1)

    print(f"\n  Re-extracting wrong_lines for: {dataset_dir}\n")
    re_extract(dataset_dir)


if __name__ == "__main__":
    main()
