"""
Paper Generator Service

AI-powered exam paper generation using question bank.
"""

import json
import random
from typing import Optional, List
from app.core.openai_client import client


def generate_paper_content(
    subject,
    template,
    questions: List,
    options: Optional[dict] = None
) -> dict:
    """
    Generate an exam paper using AI and question bank.
    
    Strategy:
    1. If template provided, use format from template
    2. Select questions based on frequency_score (weighted random)
    3. Use AI to fill gaps if question bank is insufficient
    """
    
    options = options or {}
    
    # Default format if no template
    if template and template.format_json:
        format_config = template.format_json
        total_marks = template.total_marks
        duration = template.duration_minutes
    else:
        format_config = {
            "sections": [
                {
                    "name": "Section A - Multiple Choice Questions",
                    "marks": 20,
                    "question_count": 20,
                    "question_type": "MCQ",
                    "marks_per_question": 1,
                    "compulsory": True
                },
                {
                    "name": "Section B - Descriptive Questions",
                    "marks": 40,
                    "question_count": 4,
                    "choose": 3,
                    "question_type": "Descriptive",
                    "marks_per_question": 10,
                    "compulsory": False
                }
            ]
        }
        total_marks = 60
        duration = 180
    
    # Group questions by type
    questions_by_type = {}
    for q in questions:
        qtype = q.question_type or "Descriptive"
        if qtype not in questions_by_type:
            questions_by_type[qtype] = []
        questions_by_type[qtype].append(q)
    
    # Build paper sections
    paper_sections = []
    
    for section in format_config.get("sections", []):
        section_name = section.get("name", "Section")
        question_type = section.get("question_type", "Descriptive")
        question_count = section.get("question_count", 4)
        marks_per_q = section.get("marks_per_question", section.get("marks", 10) // question_count if question_count > 0 else 10)
        
        # Select questions for this section
        available = questions_by_type.get(question_type, [])
        
        selected_questions = []
        
        if len(available) >= question_count:
            # Weighted random selection based on frequency_score
            weights = [max(q.frequency_score or 0.1, 0.1) for q in available]
            selected = random.choices(available, weights=weights, k=min(question_count, len(available)))
            
            for i, q in enumerate(selected):
                selected_questions.append({
                    "question_number": i + 1,
                    "question_text": q.question_text,
                    "marks": marks_per_q,
                    "topic": q.topic,
                    "difficulty": q.difficulty,
                    "source_question_id": q.id,
                    "options": q.options_json if question_type == "MCQ" else None
                })
        else:
            # Not enough questions in bank - use AI to generate
            selected_questions = _generate_questions_with_ai(
                subject=subject,
                question_type=question_type,
                count=question_count,
                marks=marks_per_q,
                existing=available
            )
        
        # Build instruction text
        is_compulsory = section.get("compulsory", True)
        choose = section.get("choose", question_count)
        instruction_text = "Answer all questions." if is_compulsory else f"Answer any {choose} questions."
        
        paper_sections.append({
            "section_name": section_name,
            "section_marks": section.get("marks", len(selected_questions) * marks_per_q),
            "instructions": instruction_text,
            "compulsory": section.get("compulsory", True),
            "choose": section.get("choose"),
            "questions": selected_questions
        })
    
    return {
        "title": f"{subject.name} Examination",
        "subject": subject.name,
        "subject_code": subject.code,
        "total_marks": total_marks,
        "duration_minutes": duration,
        "instructions": [
            "Read all questions carefully before attempting.",
            "All questions carry marks as indicated.",
            "Write legibly and present your answers neatly."
        ],
        "sections": paper_sections,
        "generated_at": str(datetime.now().isoformat()) if 'datetime' in dir() else None
    }


def _generate_questions_with_ai(subject, question_type: str, count: int, marks: int, existing: list) -> list:
    """
    Use AI to generate questions when question bank is insufficient.
    """
    
    # Get topics from existing questions for context
    topics = list(set(q.topic for q in existing if q.topic))
    
    # Build prompt
    topics_str = ', '.join(topics[:5]) if topics else 'General ' + subject.name
    mcq_note = "For MCQs, include 4 options (a, b, c, d) and mark the correct answer." if question_type == "MCQ" else ""
    mcq_comma = "," if question_type == "MCQ" else ""
    mcq_options = '"options": {"a": "...", "b": "...", "c": "...", "d": "...", "correct": "a"}' if question_type == "MCQ" else ""
    
    prompt = f"""
Generate {count} {question_type} questions for a {subject.name} exam.

Each question should be worth {marks} marks.

Topics to cover: {topics_str}

{mcq_note}

Return as JSON array:
[
  {{
    "question_number": 1,
    "question_text": "...",
    "marks": {marks},
    "topic": "...",
    "difficulty": "Medium"{mcq_comma}
    {mcq_options}
  }}
]
"""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": "You are an expert exam paper setter for CA (Chartered Accountancy) exams. Generate high-quality, exam-appropriate questions."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        
        output = response.choices[0].message.content.strip()
        
        # Clean JSON
        if output.startswith("```"):
            output = output.split("```")[1]
            if output.startswith("json"):
                output = output[4:]
        
        questions = json.loads(output)
        return questions
        
    except Exception as e:
        print(f"[SetterAI] AI generation failed: {e}", flush=True)
        # Return placeholder questions
        return [
            {
                "question_number": i + 1,
                "question_text": f"[Placeholder {question_type} Question {i + 1} - Please edit]",
                "marks": marks,
                "topic": "General",
                "difficulty": "Medium",
                "ai_generated": True
            }
            for i in range(count)
        ]


# Import datetime at module level
from datetime import datetime
