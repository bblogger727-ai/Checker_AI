#!/usr/bin/env python3
"""
Re-grade ONLY theory questions (Q2, Q5, Q6)
Keeps existing practical question results (Q1, Q7) to save API costs
"""

import json
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.answer_grader import collect_descriptive_enhanced

def regrade_theory_questions():
    """Re-grade only theory questions, preserve practical results"""
    
    # Load existing grading results
    grading_path = "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results/grading_final.json"
    aligned_path = "/Users/gaureshmantri/Desktop/CheckerAI/pipeline_output/aligned_answers.json"
    
    print("=" * 60)
    print("RE-GRADING THEORY QUESTIONS ONLY")
    print("=" * 60)
    
    # Load files
    with open(grading_path, 'r', encoding='utf-8') as f:
        existing_results = json.load(f)
    
    with open(aligned_path, 'r', encoding='utf-8') as f:
        aligned_answers = json.load(f)
    
    print(f"\nLoaded existing results: {grading_path}")
    print(f"Loaded aligned answers: {aligned_path}")
    
    # Identify theory questions to re-grade (not Q1, Q7)
    theory_questions = []
    
    # aligned_answers has structure: {'model_answers': {...}, 'graded_answers': {...}}
    # But we need to use existing_results structure which has the answers
    student_data = existing_results.get('graded_answers', {})
    
    for section_key, section_content in student_data.items():
        for question_key, question_content in section_content.items():
            if question_key == 'MCQ':
                continue
            
            # Skip Q1 and Q7 (practical questions already graded)
            if question_key in ['Q1', 'Q7']:
                print(f"⏭️  Skipping {question_key} (practical - already graded)")
                continue
            
            # Handle nested structure - Q1 and Q7 have nested, Q2-Q6 are flat
            if isinstance(question_content, dict):
                # Skip empty nested dict (Q2: { Q2: {} })
                if question_key in question_content and question_content[question_key] == {}:
                    # Use the outer dict (flat structure)
                    question_data = question_content
                elif question_key in question_content and isinstance(question_content[question_key], dict):
                    # Nested structure (Q1: { Q1: {...} })
                    question_data = question_content[question_key]
                else:
                    # Direct flat structure
                    question_data = question_content
                
                question_text = question_data.get('question', '')
                student_answer = question_data.get('student_answer', '')
                model_answer = question_data.get('model_answer', '')
                marks = question_data.get('marks_total', question_data.get('marks', 0))
                
                # Debug print
                if question_key in ['Q2', 'Q5', 'Q6']:
                    print(f"   [{question_key}] Answer length: {len(str(student_answer))}")
                
                # Skip unattempted
                if not student_answer or str(student_answer).strip() == '':
                    print(f"⏭️  Skipping {question_key} (not attempted)")
                    continue
                
                theory_questions.append({
                    'question_id': f"{section_key}-{question_key}",
                    'question': question_text,
                    'student_answer': student_answer,
                    'model_answer': model_answer,
                    'marks': marks,
                    'section_key': section_key,
                    'question_key': question_key
                })
    
    if not theory_questions:
        print("\n❌ No theory questions to re-grade")
        return
    
    print(f"\n📝 Re-grading {len(theory_questions)} theory questions:")
    for tq in theory_questions:
        print(f"   - {tq['question_key']} ({tq['marks']} marks)")
    
    # Grade theory questions in batch
    print(f"\n🔄 Grading theory questions in batch...")
    
    from app.services.answer_grader import grade_descriptive_batch
    
    # Prepare batch grading format
    grading_results = grade_descriptive_batch(theory_questions)
    
    # Update existing results with new theory grades
    for tq, grading in zip(theory_questions, grading_results):
        section_key = tq['section_key']
        question_key = tq['question_key']
        
        # Preserve marks_total from original question data
        grading['marks_total'] = tq['marks']
        
        # Update in existing results
        if section_key in existing_results['graded_answers']:
            if question_key in existing_results['graded_answers'][section_key]:
                # Handle nested structure
                if question_key in existing_results['graded_answers'][section_key][question_key]:
                    existing_results['graded_answers'][section_key][question_key][question_key].update(grading)
                else:
                    existing_results['graded_answers'][section_key][question_key].update(grading)
                
                print(f"✅ Updated {question_key}: {grading['marks_obtained']}/{grading['marks_total']}")
    
    # Recalculate total marks
    total_marks_obtained = 0
    total_marks_possible = 0
    
    for section_key, section_content in existing_results['graded_answers'].items():
        for question_key, question_data in section_content.items():
            if question_key == 'MCQ':
                continue
            
            # Handle nested structure
            if isinstance(question_data, dict) and question_key in question_data:
                q_data = question_data[question_key]
            else:
                q_data = question_data
            
            if isinstance(q_data, dict):
                marks_obtained = q_data.get('marks_obtained', 0)
                marks_total = q_data.get('marks_total', 0)
                
                total_marks_obtained += marks_obtained
                total_marks_possible += marks_total
    
    # Update metadata
    percentage = (total_marks_obtained / total_marks_possible * 100) if total_marks_possible > 0 else 0
    
    # Grade calculation
    if percentage >= 70:
        grade = 'A'
    elif percentage >= 60:
        grade = 'B'
    elif percentage >= 50:
        grade = 'C'
    elif percentage >= 40:
        grade = 'D'
    else:
        grade = 'F'
    
    existing_results['metadata'].update({
        'graded_at': datetime.now().isoformat(),
        'total_marks_obtained': total_marks_obtained,
        'total_marks_possible': total_marks_possible,
        'percentage': round(percentage, 2),
        'grade': grade
    })
    
    # Save updated results
    with open(grading_path, 'w', encoding='utf-8') as f:
        json.dump(existing_results, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Updated results saved to: {grading_path}")
    print(f"\n📊 Final Score: {total_marks_obtained}/{total_marks_possible} ({percentage:.2f}%) - Grade: {grade}")
    print("\n✅ Theory re-grading complete!")

if __name__ == "__main__":
    regrade_theory_questions()
