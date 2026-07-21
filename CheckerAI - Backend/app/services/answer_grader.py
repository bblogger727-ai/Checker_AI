"""
Answer Grading Service — Two-Phase System

Phase 1: COMPARISON — LLM assigns a quality tier (poor/okay/good/very_good/excellent)
Phase 2: SCORING   — LLM assigns marks within the tier's percentage band

All grading uses OCR-extracted text (no images sent to API).
"""

from app.core.openai_client import client
from difflib import SequenceMatcher
import json
import re
from datetime import datetime
from app.services.prompts import (
    THEORY_COMPARISON_PROMPT,
    PRACTICAL_COMPARISON_PROMPT,
    SCORING_PROMPT,
    MCQ_GRADING_PROMPT
)


def round_to_nearest_half(n):
    """Round number to nearest 0.5 increment."""
    return round(n * 2) / 2


# ============== MCQ GRADING (unchanged) ==============


def grade_mcq_batch(mcq_list: list) -> list:
    """
    Grade multiple MCQs via API in a single call.
    """
    if not mcq_list:
        return []

    prompt = "Grade these MCQs:\n\n"
    for mcq in mcq_list:
        prompt += f"""
---
Question {mcq['number']}: {mcq['question'][:500]}
Max Marks: {mcq['marks']}
Model Answer: {mcq['model_answer']}
Student Answer: {mcq['student_answer']}
---
"""
    prompt += "\nReturn a JSON array of objects, each with 'number', 'is_correct', 'confidence', 'reason'."

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": MCQ_GRADING_PROMPT},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = re.sub(r'^```json?\n?', '', content)
            content = re.sub(r'\n?```$', '', content)
        data = json.loads(content)
        return data.get("results", data.get("mcqs", [data] if "is_correct" in data else []))
    except Exception as e:
        print(f"[Grader] MCQ batch error: {e}", flush=True)
        return []


def grade_mcq(student_answer: str, model_answer: str, marks: int = 1, question: str = "") -> dict:
    """Grade single MCQ via API with option number priority."""
    prompt = f"""
Question: {question[:500]}
Max Marks: {marks}
Model Answer: {model_answer}
Student Answer: {student_answer}
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": MCQ_GRADING_PROMPT},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0
        )
        result = json.loads(response.choices[0].message.content.strip())
        return {
            "marks_obtained": marks if result.get("is_correct") else 0,
            "marks_total": marks,
            "is_correct": result.get("is_correct", False),
            "confidence": result.get("confidence", 0),
            "feedback": result.get("reason", "")
        }
    except Exception as e:
        return {"marks_obtained": 0, "marks_total": marks, "is_correct": False, "feedback": f"Error: {e}"}


# ============== TWO-PHASE GRADING ==============


def _phase1_compare(question_text: str, model_answer: str, student_answer: str, is_practical: bool) -> dict:
    """
    Phase 1: Send question + model + student answer → get quality tier.
    """
    system_prompt = PRACTICAL_COMPARISON_PROMPT if is_practical else THEORY_COMPARISON_PROMPT

    prompt = f"""QUESTION:
{question_text}

MODEL ANSWER:
{model_answer if model_answer else 'Not available'}

STUDENT ANSWER:
{student_answer if student_answer else 'Not provided'}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = re.sub(r'^```json?\n?', '', content)
            content = re.sub(r'\n?```$', '', content)
        result = json.loads(content)
        
        # Validate tier
        valid_tiers = ["poor", "okay", "good", "very_good", "excellent"]
        tier = result.get("tier", "poor").lower().strip()
        if tier not in valid_tiers:
            tier = "poor"
        result["tier"] = tier
        
        print(f"[Phase 1] Tier: {tier} | Reasoning: {result.get('reasoning', '')[:100]}", flush=True)
        return result
        
    except Exception as e:
        print(f"[Phase 1] Error: {e}", flush=True)
        return {"tier": "poor", "reasoning": f"Comparison error: {e}"}


def _phase2_score(question_text: str, model_answer: str, student_answer: str, marks: int, tier: str, is_practical: bool) -> dict:
    """
    Phase 2: Send question + student answer + tier → get final marks.
    """
    prompt = f"""QUESTION:
{question_text}

MODEL ANSWER:
{model_answer if model_answer else 'Not available'}

STUDENT ANSWER:
{student_answer if student_answer else 'Not provided'}

MAXIMUM MARKS: {marks}
QUALITY TIER (from comparison): {tier}

Based on the quality tier and the answer content, assign the final marks.
Follow the tier → percentage mapping strictly.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SCORING_PROMPT},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = re.sub(r'^```json?\n?', '', content)
            content = re.sub(r'\n?```$', '', content)
        result = json.loads(content)
        
        # Enforce strict rules
        raw_marks = float(result.get("marks_obtained", 0))
        max_marks = float(marks)
        
        # Rule: Never full marks
        if max_marks > 0 and raw_marks >= max_marks:
            raw_marks = max_marks - 0.5
        
        # Rule: Round to 0.5
        raw_marks = round_to_nearest_half(raw_marks)
        
        # Rule: Can't be negative
        raw_marks = max(0, raw_marks)
        
        result["marks_obtained"] = raw_marks
        result["marks_total"] = marks
        result["tier"] = tier
        result["grading_method"] = "practical_two_phase" if is_practical else "theory_two_phase"
        
        print(f"[Phase 2] Marks: {raw_marks}/{marks} (tier: {tier})", flush=True)
        return result
        
    except Exception as e:
        print(f"[Phase 2] Scoring error: {e}", flush=True)
        return {
            "marks_obtained": 0, "marks_total": marks,
            "feedback": f"Scoring error: {e}",
            "tier": tier, "grading_method": "error"
        }


def grade_two_phase(question_text: str, model_answer: str, student_answer: str, marks: int, is_practical: bool) -> dict:
    """
    Full two-phase grading: comparison → scoring.
    """
    # Handle blank/empty answers
    if not student_answer or not student_answer.strip():
        return {
            "marks_obtained": 0, "marks_total": marks,
            "feedback": "No student answer provided.",
            "tier": "poor", "grading_method": "no_answer",
            "key_points_covered": [], "key_points_missed": []
        }

    # Handle effectively-blank answers: only symbols / circled numbers / punctuation.
    # Strip all Unicode symbols, punctuation, digits, and whitespace; if nothing
    # meaningful remains, treat as no_answer (e.g. "\u2461," or "Q2" or "②.").
    import unicodedata, re
    stripped_meaningful = "".join(
        ch for ch in student_answer
        if unicodedata.category(ch).startswith("L")   # only keep actual letters
    ).strip()
    if len(stripped_meaningful) <= 3:
        return {
            "marks_obtained": 0, "marks_total": marks,
            "feedback": "No student answer provided.",
            "tier": "poor", "grading_method": "no_answer",
            "key_points_covered": [], "key_points_missed": []
        }

    # Handle heading-only answers: patterns like "Ans. 3(a)", "Answer 2b", "Q1.", "3(a)" etc.
    # These are just question labels written by the student with NO substantive content.
    import re as _re
    def _is_heading_only(text: str) -> bool:
        t = text.strip()
        # Remove common heading words
        cleaned = _re.sub(r'\b(ans(wer)?|q(uestion)?)\b\.?', '', t, flags=_re.IGNORECASE)
        # Remove question identifiers like 3(a), 2b, etc.
        cleaned = _re.sub(r'\b\d+\s*[(\[]?[a-z]?[)\]]?\b', '', cleaned, flags=_re.IGNORECASE)
        # Remove all punctuation and whitespace — if nothing left, it was only a heading
        cleaned = _re.sub(r'[\s\W]+', '', cleaned)
        return len(cleaned) == 0

    if _is_heading_only(student_answer):
        return {
            "marks_obtained": 0, "marks_total": marks,
            "feedback": "No student answer provided.",
            "tier": "poor", "grading_method": "no_answer",
            "key_points_covered": [], "key_points_missed": []
        }
    
    # Phase 1: Get quality tier
    comparison = _phase1_compare(question_text, model_answer, student_answer, is_practical)
    tier = comparison.get("tier", "poor")
    
    # Phase 2: Get marks
    scoring = _phase2_score(question_text, model_answer, student_answer, marks, tier, is_practical)
    
    # Merge Phase 1 details into final result
    if is_practical:
        scoring["correct_calculations"] = comparison.get("correct_calculations", [])
        scoring["incorrect_calculations"] = comparison.get("incorrect_calculations", [])
        scoring["missing_steps"] = comparison.get("missing_steps", [])
        scoring["final_answer_correct"] = comparison.get("final_answer_correct", False)
    else:
        # Prefer Phase 1's key point analysis (more detailed)
        if comparison.get("key_points_found"):
            scoring["key_points_covered"] = comparison.get("key_points_found", [])
        if comparison.get("key_points_missed"):
            scoring["key_points_missed"] = comparison.get("key_points_missed", [])
    
    scoring["comparison_reasoning"] = comparison.get("reasoning", "")
    return scoring


# ============== QUESTION TYPE DETECTION ==============


def is_practical_question(question_text: str) -> bool:
    """Heuristic to identify practical/calculation questions."""
    keywords = ["compute", "calculate", "determine the taxable", "total income",
                 "assessable value", "net gst", "gst payable", "tax liability",
                 "tds", "tcs", "refund", "input tax credit"]
    q_lower = question_text.lower()
    return any(k in q_lower for k in keywords) and len(question_text) > 50


# ============== OR GROUP HANDLING ==============


def extract_or_groups(model_answers: dict) -> dict:
    """
    Extract OR groups from model answers schema.
    
    Returns:
        Dict mapping or_group -> list of question_ids in that group
    """
    or_groups = {}
    
    def scan_for_or_groups(data, prefix=""):
        if isinstance(data, dict):
            or_group = data.get("or_group")
            qid = data.get("question_id")
            
            if or_group and qid:
                if or_group not in or_groups:
                    or_groups[or_group] = []
                or_groups[or_group].append(qid)
            
            for key, value in data.items():
                scan_for_or_groups(value, f"{prefix}.{key}" if prefix else key)
    
    scan_for_or_groups(model_answers)
    return or_groups


def determine_attempted_question(or_group_qids: list, student_answers: dict) -> str:
    """
    Determine which question in an OR group the student actually attempted.
    
    Returns the question_id that has the most substantial answer.
    """
    best_qid = or_group_qids[0]
    best_len = 0
    
    def find_answer(data, target_qid):
        if isinstance(data, dict):
            if data.get("question_id") == target_qid:
                return data.get("student_answer", "")
            for value in data.values():
                result = find_answer(value, target_qid)
                if result is not None:
                    return result
        return None
    
    for qid in or_group_qids:
        answer = find_answer(student_answers, qid)
        if answer and len(str(answer)) > best_len:
            best_len = len(str(answer))
            best_qid = qid
    
    return best_qid


def get_skipped_or_questions(model_answers: dict, student_answers: dict) -> set:
    """
    Get set of question_ids that should be skipped because they are
    unattempted alternatives in OR groups.
    """
    or_groups = extract_or_groups(model_answers)
    skip_ids = set()
    
    for group_name, qids in or_groups.items():
        if len(qids) <= 1:
            continue
        
        attempted = determine_attempted_question(qids, student_answers)
        for qid in qids:
            if qid != attempted:
                skip_ids.add(qid)
    
    return skip_ids


def calculate_grade(percentage: float) -> str:
    """Convert percentage to letter grade."""
    if percentage >= 60: return "A"
    elif percentage >= 50: return "B"
    elif percentage >= 40: return "C"
    elif percentage >= 33: return "D"
    else: return "F"


# ============== MAIN GRADING FUNCTION ==============


def grade_all_answers(aligned_answers: dict, model_answers: dict, student_pdf_path: str = None) -> dict:
    """
    Grade all student answers against model answers.
    Uses two-phase text-based grading for all questions.
    student_pdf_path is kept for backward compatibility but NOT used for grading.
    """
    graded_results = {}
    mcq_count = 0
    descriptive_count = 0
    
    # Handle wrapper
    student_data = aligned_answers.get("aligned_answers", aligned_answers)
    if "aligned_answers" in student_data:
        student_data = student_data["aligned_answers"]
    
    # Detect OR groups
    skip_or_questions = get_skipped_or_questions(model_answers, student_data)
    
    # Process sections
    for section_key, section_content in student_data.items():
        if section_key in ["status", "metadata"]:
            continue
        
        graded_results[section_key] = {}
        
        for question_key, question_content in section_content.items():
            
            if question_key == "MCQ":
                # MCQ grading (unchanged)
                graded_results[section_key]["MCQ"] = {}
                model_mcqs = model_answers.get(section_key, {}).get("MCQ", {})
                
                for mcq_num, mcq_data in question_content.items():
                    student_ans = mcq_data.get("student_answer", "")
                    question_text = mcq_data.get("question", "")
                    model_mcq = model_mcqs.get(mcq_num, {})
                    model_ans = model_mcq.get("model_answer", "")
                    marks = model_mcq.get("marks", 2)
                    
                    mcq_result = grade_mcq(
                        student_ans, model_ans,
                        marks=int(marks) if str(marks).isdigit() else 2,
                        question=question_text
                    )
                    
                    graded_results[section_key]["MCQ"][mcq_num] = {
                        "question": question_text,
                        "student_answer": student_ans,
                        "model_answer": model_ans,
                        **mcq_result
                    }
                    mcq_count += 1
            
            else:
                # Descriptive/Practical — two-phase grading
                graded_results[section_key][question_key] = {}
                model_q = model_answers.get(section_key, {}).get(question_key, {})
                
                _grade_question_recursive(
                    question_key, question_content, model_q,
                    f"{section_key}-{question_key}",
                    graded_results[section_key][question_key],
                    skip_or_questions
                )
    
    # Calculate totals
    all_graded_items = _flatten_results(graded_results)
    total_marks_obtained = sum(item.get("marks_obtained", 0) for item in all_graded_items)
    total_marks_possible = sum(item.get("marks_total", 0) for item in all_graded_items)
    descriptive_count = len([i for i in all_graded_items if "MCQ" not in str(i.get("question_id", ""))])
    mcq_count = len([i for i in all_graded_items if "MCQ" in str(i.get("question_id", ""))])
    
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


def _flatten_results(data):
    """Recursively extract all graded items from nested result structure."""
    items = []
    if isinstance(data, dict):
        if "marks_obtained" in data and "marks_total" in data:
            items.append(data)
        for v in data.values():
            items.extend(_flatten_results(v))
    return items


def _grade_question_recursive(q_key, q_content, model_q, qid, result_ref, skip_ids):
    """
    Recursively grade descriptive/practical questions using two-phase system.
    All questions use text-based grading (no images).
    """
    if skip_ids is None:
        skip_ids = set()
    
    if isinstance(q_content, dict) and "student_answer" in q_content:
        question_id = model_q.get("question_id", qid) if isinstance(model_q, dict) else qid
        
        # Check skip (OR alternative)
        if question_id in skip_ids:
            result_ref[q_key] = {
                "question": q_content.get("question", ""),
                "marks_obtained": 0, "marks_total": 0,
                "feedback": "Skipped (OR alternative)",
                "skipped_or_alternative": True
            }
            return
        
        question_text = q_content.get("question", "")
        student_ans = q_content.get("student_answer", "")
        model_ans = model_q.get("model_answer", "") if isinstance(model_q, dict) else ""
        marks = 5
        if isinstance(model_q, dict):
            m = model_q.get("marks", 5)
            marks = int(m) if str(m).isdigit() else 5
        
        # Detect question type
        practical = is_practical_question(question_text) or marks >= 8
        
        print(f"[Grader] Two-phase grading: {question_id} ({'practical' if practical else 'theory'}, {marks} marks)", flush=True)
        
        # Grade via two-phase system
        grading = grade_two_phase(question_text, model_ans, student_ans, marks, practical)
        
        result_ref[q_key] = {
            "question": question_text,
            "student_answer": student_ans,
            "model_answer": model_ans,
            "marks_obtained": grading.get("marks_obtained", 0),
            "marks_total": marks,
            "feedback": grading.get("feedback", ""),
            "tier": grading.get("tier", ""),
            "grading_method": grading.get("grading_method", ""),
            "key_points_covered": grading.get("key_points_covered", []),
            "key_points_missed": grading.get("key_points_missed", []),
            "major_errors": grading.get("major_errors", []),
            "correct_items": grading.get("correct_items", [])
        }
        
    elif isinstance(q_content, dict):
        # Nested subparts
        for sub_key, sub_content in q_content.items():
            if sub_key in ["question", "student_answer", "answer_pages", "question_id",
                          "question_number", "subpart", "marks", "or_group", "model_answer"]:
                continue
            result_ref[sub_key] = {}
            sub_model = model_q.get(sub_key, {}) if isinstance(model_q, dict) else {}
            _grade_question_recursive(
                sub_key, sub_content, sub_model,
                f"{qid}-{sub_key}", result_ref[sub_key], skip_ids
            )
