"""
Answer Grading Service

Efficient grading by sending:
- Complete model answers schema (with model_answer for each question)
- Complete student answers (aligned to same schema)
- One API call to grade ALL together

MCQs still use fuzzy matching for speed/cost.
Descriptive questions sent in batches to GPT.
"""

from app.core.openai_client import client
from difflib import SequenceMatcher
import json
import re
from datetime import datetime


# ============== MCQ GRADING (Fuzzy Match - Free & Fast) ==============

def normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    if not text:
        return ""
    
    text = text.lower().strip()
    text = re.sub(r'₹|rs\.?|inr', '', text, flags=re.IGNORECASE)
    text = re.sub(r'(\d),(\d)', r'\1\2', text)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[.,;:\-\(\)]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text


def fuzzy_match_score(student_answer: str, model_answer: str) -> float:
    """Calculate similarity ratio between two strings."""
    if not student_answer or not model_answer:
        return 0.0
    
    norm_student = normalize_text(student_answer)
    norm_model = normalize_text(model_answer)
    
    if not norm_student or not norm_model:
        return 0.0
    
    if norm_student == norm_model:
        return 1.0
    
    if norm_model in norm_student or norm_student in norm_model:
        return 0.9
    
    return SequenceMatcher(None, norm_student, norm_model).ratio()


def grade_mcq(student_answer: str, model_answer: str, marks: int = 1) -> dict:
    """Grade MCQ using fuzzy string matching."""
    similarity = fuzzy_match_score(student_answer, model_answer)
    is_correct = similarity >= 0.7
    
    return {
        "marks_obtained": marks if is_correct else 0,
        "marks_total": marks,
        "is_correct": is_correct,
        "similarity_score": round(similarity, 2),
        "feedback": "Correct" if is_correct else f"Incorrect. Expected: {model_answer}"
    }


# ============== DESCRIPTIVE GRADING (GPT - Batch) ==============

GRADING_SYSTEM_PROMPT = """You are an expert CA exam evaluator.

You will receive:
1. A list of questions with their model answers and marks
2. The corresponding student answers for each question

For EACH question, evaluate the student answer against the model answer and provide:
{
  "question_id": "<the question ID>",
  "marks_obtained": <integer between 0 and marks_total>,
  "feedback": "<concise feedback explaining the grade>",
  "key_points_covered": ["point1", "point2"],
  "key_points_missed": ["point1", "point2"]
}

GRADING RULES:
- Award marks based on correctness and completeness
- Partial marks allowed for partially correct answers
- Consider conceptual understanding, not just exact wording
- For numerical questions, check calculations
- If student answer is empty, give 0 marks with feedback "No answer provided"

Return a JSON array with grading for EACH question.
Return ONLY valid JSON array, no markdown."""


def grade_descriptive_batch(questions_with_answers: list) -> list:
    """
    Grade multiple descriptive questions in a single API call.
    
    Args:
        questions_with_answers: List of dicts with question_id, question, model_answer, student_answer, marks
    
    Returns:
        List of grading results
    """
    if not questions_with_answers:
        return []
    
    # Build prompt with all questions
    prompt = "Grade these student answers:\n\n"
    
    for q in questions_with_answers:
        prompt += f"""
---
Question ID: {q['question_id']}
Marks: {q['marks']}

Question: {q['question'][:500]}...

Model Answer: {q['model_answer'][:1000] if q['model_answer'] else 'Not available'}

Student Answer: {q['student_answer'][:1000] if q['student_answer'] else 'Not provided'}
---
"""
    
    prompt += "\nProvide grading for ALL questions above as a JSON array."
    
    try:
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": GRADING_SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )
        
        content = response.choices[0].message.content.strip()
        
        if content.startswith("```"):
            content = re.sub(r'^```json?\n?', '', content)
            content = re.sub(r'\n?```$', '', content)
        
        results = json.loads(content)
        return results if isinstance(results, list) else [results]
        
    except Exception as e:
        print(f"[Grader] Batch grading error: {e}", flush=True)
        # Return default grading for all
        return [
            {
                "question_id": q['question_id'],
                "marks_obtained": 0,
                "feedback": "Grading error - please review manually",
                "key_points_covered": [],
                "key_points_missed": []
            }
            for q in questions_with_answers
        ]


# ============== MAIN GRADING FUNCTION ==============

def calculate_grade(percentage: float) -> str:
    """Convert percentage to letter grade."""
    if percentage >= 90: return "A+"
    elif percentage >= 80: return "A"
    elif percentage >= 70: return "B+"
    elif percentage >= 60: return "B"
    elif percentage >= 50: return "C"
    elif percentage >= 40: return "D"
    else: return "F"


def grade_all_answers(aligned_answers: dict, model_answers: dict) -> dict:
    """
    Grade all student answers against model answers.
    
    - MCQs: Fuzzy string matching (instant, free)
    - Descriptive: Batched GPT evaluation (efficient)
    
    Args:
        aligned_answers: Dict with student answers aligned to schema
        model_answers: Dict with model answers for each question
    
    Returns:
        Complete grading results
    """
    graded_results = {}
    total_marks_obtained = 0
    total_marks_possible = 0
    mcq_count = 0
    descriptive_count = 0
    
    # Collect descriptive questions for batch processing
    descriptive_questions = []
    
    # Handle wrapper
    student_data = aligned_answers.get("aligned_answers", aligned_answers)
    if "aligned_answers" in student_data:
        student_data = student_data["aligned_answers"]
    
    # First pass: Grade MCQs and collect descriptive questions
    for section_key, section_content in student_data.items():
        if section_key in ["status", "metadata"]:
            continue
            
        graded_results[section_key] = {}
        
        for question_key, question_content in section_content.items():
            
            if question_key == "MCQ":
                graded_results[section_key]["MCQ"] = {}
                model_mcqs = model_answers.get(section_key, {}).get("MCQ", {})
                
                for mcq_num, mcq_data in question_content.items():
                    student_ans = mcq_data.get("student_answer", "") if isinstance(mcq_data, dict) else ""
                    question_text = mcq_data.get("question", "") if isinstance(mcq_data, dict) else str(mcq_data)
                    
                    model_mcq = model_mcqs.get(mcq_num, {})
                    model_ans = model_mcq.get("model_answer", "") if isinstance(model_mcq, dict) else ""
                    marks = model_mcq.get("marks", 1) if isinstance(model_mcq, dict) else 1
                    if isinstance(marks, str):
                        marks = int(marks) if marks.isdigit() else 1
                    
                    mcq_result = grade_mcq(student_ans, model_ans, marks=1)  # MCQs are 1 mark each
                    
                    graded_results[section_key]["MCQ"][mcq_num] = {
                        "question": question_text,
                        "student_answer": student_ans,
                        "model_answer": model_ans,
                        **mcq_result
                    }
                    
                    total_marks_obtained += mcq_result["marks_obtained"]
                    total_marks_possible += mcq_result["marks_total"]
                    mcq_count += 1
            
            else:
                # Collect descriptive questions
                graded_results[section_key][question_key] = {}
                model_q = model_answers.get(section_key, {}).get(question_key, {})
                
                collect_descriptive(
                    question_key, question_content, model_q,
                    f"{section_key}-{question_key}",
                    descriptive_questions,
                    graded_results[section_key][question_key]
                )
    
    # Second pass: Batch grade all descriptive questions
    print(f"[Grader] Grading {len(descriptive_questions)} descriptive questions in batch...", flush=True)
    
    if descriptive_questions:
        # Process in batches of 10 to avoid token limits
        batch_size = 10
        all_gradings = []
        
        for i in range(0, len(descriptive_questions), batch_size):
            batch = descriptive_questions[i:i+batch_size]
            print(f"[Grader] Processing batch {i//batch_size + 1}...", flush=True)
            batch_results = grade_descriptive_batch(batch)
            all_gradings.extend(batch_results)
        
        # Map results back to graded_results
        grading_map = {g["question_id"]: g for g in all_gradings}
        
        for q in descriptive_questions:
            qid = q["question_id"]
            grading = grading_map.get(qid, {})
            
            marks_total = q["marks"]
            marks_obtained = min(grading.get("marks_obtained", 0), marks_total)
            
            # Navigate to the right place in graded_results
            result_entry = q["result_ref"]
            result_entry.update({
                "question": q["question"],
                "student_answer": q["student_answer"],
                "model_answer": q["model_answer"],
                "marks_obtained": marks_obtained,
                "marks_total": marks_total,
                "feedback": grading.get("feedback", ""),
                "key_points_covered": grading.get("key_points_covered", []),
                "key_points_missed": grading.get("key_points_missed", [])
            })
            
            total_marks_obtained += marks_obtained
            total_marks_possible += marks_total
            descriptive_count += 1
    
    # Calculate summary
    percentage = (total_marks_obtained / total_marks_possible * 100) if total_marks_possible > 0 else 0
    
    return {
        "metadata": {
            "graded_at": datetime.now().isoformat(),
            "total_questions": mcq_count + descriptive_count,
            "mcq_questions": mcq_count,
            "descriptive_questions": descriptive_count,
            "total_marks_possible": total_marks_possible,
            "total_marks_obtained": total_marks_obtained,
            "percentage": round(percentage, 2),
            "grade": calculate_grade(percentage)
        },
        "graded_answers": graded_results
    }


def collect_descriptive(q_key, q_content, model_q, qid, collection, result_ref):
    """Recursively collect descriptive questions for batch processing."""
    
    if isinstance(q_content, dict) and "student_answer" in q_content:
        # Leaf question
        marks = 5
        if isinstance(model_q, dict):
            marks = model_q.get("marks", 5)
            if isinstance(marks, str):
                marks = int(marks) if marks.isdigit() else 5
        
        entry = {}
        result_ref[q_key] = entry if q_key not in result_ref else result_ref
        
        collection.append({
            "question_id": qid,
            "question": q_content.get("question", ""),
            "student_answer": q_content.get("student_answer", ""),
            "model_answer": model_q.get("model_answer", "") if isinstance(model_q, dict) else "",
            "marks": marks,
            "result_ref": result_ref if q_key in result_ref else entry
        })
        
    elif isinstance(q_content, dict):
        # Nested structure
        for sub_key, sub_content in q_content.items():
            if sub_key in ["question", "student_answer"]:
                continue
            result_ref[sub_key] = {}
            sub_model = model_q.get(sub_key, {}) if isinstance(model_q, dict) else {}
            collect_descriptive(sub_key, sub_content, sub_model, f"{qid}-{sub_key}", collection, result_ref[sub_key])
