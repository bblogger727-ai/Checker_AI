#!/usr/bin/env python3
"""
STAGE 5B: Grading (TEXT-BASED For Practical Questions - EXPERIMENTAL)

This is an EXPERIMENTAL variant that uses OCR text instead of images 
for practical questions. Same strict numerical grading prompt, different input method.

Output: grading_results/grading_final_TEXT.json (separate file for comparison)
"""

import sys
import os
import json
import argparse

# Add parent directory to path to import app modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.answer_grader import (
    grade_practical_text,
    grade_descriptive_batch,
    is_practical_question,
    round_to_nearest_half,
    calculate_grade,
    get_skipped_or_questions
)
from datetime import datetime


def grade_all_answers_text_mode(aligned_answers: dict) -> dict:
    """
    Modified grading function that uses TEXT-BASED grading for practical questions
    instead of image-based grading.
    
    This is experimental to compare against image grading.
    """
    graded_results = {}
    total_marks_obtained = 0
    total_marks_possible = 0
    descriptive_count = 0
    
    # Collect NON-practical descriptive questions for batch processing
    descriptive_questions = []
    
    # Handle wrapper
    student_data = aligned_answers.get("aligned_answers", aligned_answers)
    if "aligned_answers" in student_data:
        student_data = student_data["aligned_answers"]
    
    # Detect OR groups (no model_answers dict here, so skip this)
    # We'll just grade everything
    
    # Process sections
    for section_key, section_content in student_data.items():
        if section_key in ["status", "metadata"]: 
            continue
            
        graded_results[section_key] = {}
        
        for question_key, question_content in section_content.items():
            if question_key == "MCQ":
                graded_results[section_key]["MCQ"] = {}
                continue  # Skip MCQs for now
            
            # Assume all questions except MCQ are descriptive
            if not isinstance(question_content, dict):
                continue
            
            question_text = question_content.get("question", "")
            student_answer = question_content.get("student_answer", "")
            model_answer = question_content.get("model_answer", "")
            marks = question_content.get("marks", 5)
            
            if not marks: 
                marks = 5
            marks = int(marks) if str(marks).isdigit() else 5
            
            # Check if practical
            is_practical = is_practical_question(question_text) or marks >= 8
            
            if is_practical and student_answer:
                # GRADE WITH TEXT instead of image
                print(f"[Grader TEXT] Grading practical question {question_key} using OCR TEXT...", flush=True)
                grading = grade_practical_text(
                    question_text=question_text,
                    model_answer=model_answer,
                    marks=marks,
                    student_answer_text=student_answer
                )
                
                graded_results[section_key][question_key] = {
                    "question": question_text,
                    "student_answer": student_answer,
                    "model_answer": model_answer,
                    "marks_obtained": grading.get("marks_obtained", 0),
                    "marks_total": marks,
                    "feedback": grading.get("feedback", ""),
                    "major_errors": grading.get("major_errors", []),
                    "correct_items": grading.get("correct_items", []),
                    "grading_method": "strict_text_practical"
                }
                
                total_marks_obtained += grading.get("marks_obtained", 0)
                total_marks_possible += marks
                descriptive_count += 1
                
            else:
                # Non-practical descriptive - collect for batch
                descriptive_questions.append({
                    "question_id": f"{section_key}-{question_key}",
                    "question": question_text,
                    "student_answer": student_answer,
                    "model_answer": model_answer,
                    "marks": marks,
                    "result_ref": graded_results[section_key],
                    "result_key": question_key
                })
    
    # Batch grade non-practical descriptive questions
    if descriptive_questions:
        print(f"[Grader TEXT] Grading {len(descriptive_questions)} non-practical descriptive questions in batch...", flush=True)
        batch_results = grade_descriptive_batch(descriptive_questions)
        
        for i, q in enumerate(descriptive_questions):
            grading = batch_results[i] if i < len(batch_results) else {}
            
            # Apply strictness rules
            marks_total = q["marks"]
            raw_marks = grading.get("marks_obtained", 0)
            
            # Never full marks
            if marks_total > 0 and raw_marks >= marks_total:
                raw_marks = marks_total - 0.5
                grading["feedback"] = grading.get("feedback", "") + " [Strictness: Max marks capped]"
            
            # Length check
            m_len = len(str(q.get("model_answer", "")))
            s_len = len(str(q.get("student_answer", "")))
            if m_len > 100 and s_len < (m_len * 0.4):
                capped_len_marks = marks_total * 0.4
                if raw_marks > capped_len_marks:
                    raw_marks = capped_len_marks
                    grading["feedback"] += " [Strictness: Penalized for brevity]"

            marks_obtained = min(raw_marks, marks_total)
            marks_obtained = round_to_nearest_half(marks_obtained)
            
            result_dict = {
                "question": q["question"],
                "student_answer": q["student_answer"],
                "model_answer": q["model_answer"],
                "marks_obtained": marks_obtained,
                "marks_total": marks_total,
                "feedback": grading.get("feedback", ""),
                "key_points_covered": grading.get("key_points_covered", []),
                "key_points_missed": grading.get("key_points_missed", [])
            }
            
            q["result_ref"][q["result_key"]] = result_dict
            
            total_marks_obtained += marks_obtained
            total_marks_possible += marks_total
            descriptive_count += 1
    
    percentage = (total_marks_obtained / total_marks_possible * 100) if total_marks_possible > 0 else 0
    
    return {
        "metadata": {
            "graded_at": datetime.now().isoformat(),
            "grading_mode": "TEXT_BASED_PRACTICAL (Experimental)",
            "total_questions": descriptive_count,
            "mcq_questions": 0,
            "descriptive_questions": descriptive_count,
            "total_marks_possible": total_marks_possible,
            "total_marks_obtained": total_marks_obtained,
            "percentage": round(percentage, 2),
            "grade": calculate_grade(percentage)
        },
        "graded_answers": graded_results
    }


def main():
    parser = argparse.ArgumentParser(description="Stage 5B: Grade using TEXT for practical questions (EXPERIMENTAL)")
    parser.add_argument("--as", dest="student_pdf", help="Path to student answer script PDF (unused in text mode)", default=None)
    args = parser.parse_args()
    
    print("=" * 60)
    print("STAGE 5B: Grading (TEXT-BASED PRACTICAL - EXPERIMENTAL)")
    print("=" * 60)
    
    aligned_answers_path = "/Users/gaureshmantri/Desktop/CheckerAI/pipeline_output/aligned_answers.json"
    output_path = "grading_results/grading_final_TEXT.json"
    
    # Check prerequisites
    if not os.path.exists(aligned_answers_path):
        print(f"❌ Missing: {aligned_answers_path}")
        print("   Run: python3 run_stage_4_alignment.py")
        return 1
    
    print(f"Aligned answers: {os.path.abspath(aligned_answers_path)}")
    print("Grading answers using TEXT for practical questions...")
    
    # Load aligned answers
    with open(aligned_answers_path, 'r') as f:
        aligned_answers = json.load(f)
    
    # Grade all
    grading_results = grade_all_answers_text_mode(aligned_answers)
    
    # Create output directory
    os.makedirs("grading_results", exist_ok=True)
    
    # Save results
    with open(output_path, 'w') as f:
        json.dump(grading_results, f, indent=2)
    
    print(f"✓ Grading results saved to: {os.path.abspath(output_path)}")
    
    # Print summary
    meta = grading_results["metadata"]
    print(f"\n  Score: {meta['total_marks_obtained']}/{meta['total_marks_possible']}")
    print(f"  Percentage: {meta['percentage']}%")
    print(f"  Grade: {meta['grade']}")
    print(f"  Mode: {meta['grading_mode']}")
    
    print("\nDone. Compare with grading_final.json to see differences!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
