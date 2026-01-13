"""
Solution Generator Service

Auto-generate solutions for finalized papers using question bank answers and AI.
"""

import json
from typing import List, Optional
from app.core.openai_client import client


def generate_solution(
    paper_json: dict,
    subject,
    question_bank: List,
    reference_materials: Optional[str] = None
) -> dict:
    """
    Generate a complete solution for a paper.
    
    Strategy:
    1. For questions from question bank, use stored model_answer
    2. For AI-generated questions, generate answer using LLM
    3. Compile into solution format
    """
    
    # Build lookup for question bank answers
    qb_answers = {}
    for q in question_bank:
        qb_answers[q.id] = q.model_answer
    
    solution_sections = []
    
    for section in paper_json.get("sections", []):
        section_solutions = []
        
        for question in section.get("questions", []):
            q_num = question.get("question_number", "?")
            q_text = question.get("question_text", "")
            marks = question.get("marks", 0)
            source_id = question.get("source_question_id")
            options = question.get("options")
            
            # Try to get answer from question bank
            answer = None
            if source_id and source_id in qb_answers:
                answer = qb_answers[source_id]
            
            # If MCQ, answer is the correct option
            if options and "correct" in options:
                correct_key = options["correct"]
                answer = f"Correct Answer: ({correct_key}) {options.get(correct_key, '')}"
            
            # If no answer found, generate with AI
            if not answer:
                answer = _generate_answer_with_ai(
                    question_text=q_text,
                    marks=marks,
                    subject_name=subject.name,
                    reference=reference_materials
                )
            
            section_solutions.append({
                "question_number": q_num,
                "question_text": q_text[:200] + "..." if len(q_text) > 200 else q_text,
                "marks": marks,
                "model_answer": answer,
                "marking_guide": _generate_marking_guide(marks)
            })
        
        solution_sections.append({
            "section_name": section.get("section_name"),
            "solutions": section_solutions
        })
    
    return {
        "title": f"Solution - {paper_json.get('title', 'Exam')}",
        "subject": subject.name,
        "total_marks": paper_json.get("total_marks"),
        "sections": solution_sections,
        "general_instructions": [
            "Award marks for correct steps even if final answer is wrong.",
            "Accept alternative correct approaches.",
            "Deduct marks for calculation errors but give credit for correct method."
        ]
    }


def _generate_answer_with_ai(
    question_text: str,
    marks: int,
    subject_name: str,
    reference: Optional[str] = None
) -> str:
    """Generate model answer using AI."""
    
    prompt = f"""
Provide a model answer for this {subject_name} exam question worth {marks} marks:

Question:
{question_text}

{f'Reference material: {reference[:1000]}' if reference else ''}

Requirements:
- Answer should be comprehensive enough to earn full {marks} marks
- Include step-by-step working where applicable
- Be precise and exam-appropriate
- For calculations, show all steps
"""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": f"You are an expert CA examiner providing model answers for {subject_name}. Be thorough but concise."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        
        return response.choices[0].message.content.strip()
        
    except Exception as e:
        print(f"[SetterAI] Solution generation failed: {e}", flush=True)
        return f"[Model answer to be added - {marks} marks]"


def _generate_marking_guide(marks: int) -> list:
    """Generate marking distribution guide."""
    
    if marks <= 1:
        return ["Full marks for correct answer"]
    elif marks <= 4:
        return [
            f"Correct concept: {marks // 2} marks",
            f"Correct application: {marks - (marks // 2)} marks"
        ]
    else:
        return [
            f"Understanding/Definition: {marks // 4} marks",
            f"Explanation/Steps: {marks // 2} marks",
            f"Correct conclusion: {marks - (marks // 4) - (marks // 2)} marks"
        ]
