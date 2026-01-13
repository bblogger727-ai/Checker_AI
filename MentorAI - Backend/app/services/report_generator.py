"""
Report Generator Service

Generates personalized PDF reports using LLM.
"""

import os
import json
from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session

from app.core.openai_client import client
from app.models import Student, StudentExam, Consultation, Problem


def generate_report(
    student: Student,
    exams: List[StudentExam],
    current_problems: List[dict],
    custom_problem: Optional[str],
    past_consultations: List[Consultation],
    mentor_notes: Optional[str],
    db: Session
) -> dict:
    """
    Generate a personalized progress report using LLM.
    
    Returns:
        dict with prompt, llm_response, solution, pdf_path
    """
    
    # Build context for LLM
    exam_summary = _build_exam_summary(exams)
    problem_summary = _build_problem_summary(current_problems, custom_problem)
    history_summary = _build_history_summary(past_consultations, db)
    
    prompt = f"""You are an expert CA (Chartered Accountancy) student mentor. Generate a personalized, encouraging, and actionable progress report for a student.

## STUDENT INFORMATION
Name: {student.name}
Student ID: {student.student_id}
Date: {datetime.now().strftime("%d %B %Y")}

## EXAM PERFORMANCE
{exam_summary}

## CURRENT PROBLEMS IDENTIFIED
{problem_summary}

## PAST CONSULTATION HISTORY
{history_summary}

{f"## MENTOR'S NOTES FOR THIS SESSION{chr(10)}{mentor_notes}" if mentor_notes else ""}

---

Please generate a comprehensive report with the following sections:

1. **PERFORMANCE SUMMARY** (2-3 sentences analyzing their exam trend)

2. **THIS WEEK'S FOCUS AREA** (Acknowledge the problems identified)

3. **PERSONALIZED RECOMMENDATIONS** (Detailed, actionable advice for each problem. If this problem was identified before, acknowledge that and provide NEW approaches since the previous solution may not have worked fully.)

4. **ACTION ITEMS FOR THIS WEEK** (5-7 specific, measurable tasks they should complete)

5. **MOTIVATION** (A brief encouraging message tailored to their situation)

Be warm, supportive, but also practical. Use the student's name naturally. If they're improving, celebrate it. If declining, be encouraging but honest about the need for change.
"""

    llm_response = None
    solution = None
    
    if client:
        try:
            response = client.chat.completions.create(
                model="gpt-4.1",
                messages=[
                    {"role": "system", "content": "You are a caring, experienced CA mentor who has helped hundreds of students succeed. You provide personalized, actionable advice."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=2000
            )
            llm_response = response.choices[0].message.content
            solution = llm_response
        except Exception as e:
            print(f"[MentorAI] LLM Error: {e}", flush=True)
            solution = _generate_fallback_solution(current_problems, custom_problem)
            llm_response = f"Error: {str(e)}"
    else:
        solution = _generate_fallback_solution(current_problems, custom_problem)
        llm_response = "LLM not configured"
    
    # Generate PDF
    pdf_path = _generate_pdf(student, exams, current_problems, custom_problem, solution)
    
    return {
        "prompt": prompt,
        "llm_response": llm_response,
        "solution": solution,
        "pdf_path": pdf_path
    }


def _build_exam_summary(exams: List[StudentExam]) -> str:
    """Build exam summary for LLM context."""
    if not exams:
        return "No exam records available yet."
    
    lines = ["Recent exams (newest first):"]
    for exam in exams[:5]:
        grade_str = f" ({exam.grade})" if exam.grade else ""
        lines.append(f"- {exam.exam_name}: {exam.obtained_marks}/{exam.total_marks} ({exam.percentage:.1f}%){grade_str}")
    
    # Calculate trend
    if len(exams) >= 2:
        recent_avg = sum(e.percentage or 0 for e in exams[:3]) / min(3, len(exams))
        older_avg = sum(e.percentage or 0 for e in exams[3:6]) / min(3, len(exams) - 3) if len(exams) > 3 else recent_avg
        
        if recent_avg > older_avg + 2:
            lines.append(f"\nTrend: IMPROVING (recent avg {recent_avg:.1f}% vs earlier {older_avg:.1f}%)")
        elif recent_avg < older_avg - 2:
            lines.append(f"\nTrend: DECLINING (recent avg {recent_avg:.1f}% vs earlier {older_avg:.1f}%)")
        else:
            lines.append(f"\nTrend: STABLE (around {recent_avg:.1f}%)")
    
    return "\n".join(lines)


def _build_problem_summary(problems: List[dict], custom_problem: Optional[str]) -> str:
    """Build problem summary for LLM context."""
    if not problems and not custom_problem:
        return "No specific problems identified in this session."
    
    lines = []
    for p in problems:
        category = p.get("category", "General")
        title = p.get("title", "Unknown")
        default_sol = p.get("default_solution", "")
        notes = p.get("notes", "")
        
        lines.append(f"- [{category}] {title}")
        if notes:
            lines.append(f"  Mentor notes: {notes}")
        if default_sol:
            lines.append(f"  Standard recommendation: {default_sol}")
    
    if custom_problem:
        lines.append(f"- [Other] {custom_problem}")
    
    return "\n".join(lines)


def _build_history_summary(past_consultations: List[Consultation], db: Session) -> str:
    """Build past consultation history for LLM context."""
    if not past_consultations:
        return "This is the first consultation with this student."
    
    lines = ["Previous sessions:"]
    for consult in past_consultations[:3]:
        date_str = consult.consultation_date.strftime("%d %b %Y") if consult.consultation_date else "Unknown date"
        
        # Get problem titles
        problem_titles = []
        if consult.problems_json:
            for p in consult.problems_json:
                problem = db.query(Problem).filter(Problem.id == p.get("problem_id")).first()
                if problem:
                    problem_titles.append(problem.title)
        
        if consult.custom_problem_text:
            problem_titles.append(consult.custom_problem_text)
        
        problems_str = ", ".join(problem_titles) if problem_titles else "General consultation"
        
        lines.append(f"\n{date_str}:")
        lines.append(f"  Problems: {problems_str}")
        
        if consult.generated_solution:
            # Show first 200 chars of previous solution
            preview = consult.generated_solution[:300].replace("\n", " ")
            lines.append(f"  Solution given: {preview}...")
    
    return "\n".join(lines)


def _generate_fallback_solution(problems: List[dict], custom_problem: Optional[str]) -> str:
    """Generate a basic solution when LLM is unavailable."""
    lines = ["# Progress Report\n"]
    lines.append("## Recommendations\n")
    
    for p in problems:
        title = p.get("title", "Issue")
        solution = p.get("default_solution", "Follow up with mentor for detailed guidance.")
        lines.append(f"### {title}")
        lines.append(f"{solution}\n")
    
    if custom_problem:
        lines.append(f"### Other: {custom_problem}")
        lines.append("Discuss with mentor for personalized guidance.\n")
    
    lines.append("## Action Items")
    lines.append("- Review the recommendations above")
    lines.append("- Create a weekly study schedule")
    lines.append("- Check in with mentor next week")
    
    return "\n".join(lines)


def _generate_pdf(
    student: Student,
    exams: List[StudentExam],
    problems: List[dict],
    custom_problem: Optional[str],
    solution: str
) -> str:
    """
    Generate PDF report.
    For now, saves as text file. Can be upgraded to proper PDF later.
    """
    
    # Create reports directory
    reports_dir = "data/reports"
    os.makedirs(reports_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{student.student_id}_{timestamp}.txt"
    filepath = os.path.join(reports_dir, filename)
    
    # Build report content
    content = []
    content.append("=" * 60)
    content.append("         STUDENT PROGRESS REPORT")
    content.append("=" * 60)
    content.append(f"\nStudent: {student.name}")
    content.append(f"ID: {student.student_id}")
    content.append(f"Date: {datetime.now().strftime('%d %B %Y')}")
    content.append("\n" + "-" * 60)
    
    # Exam summary
    content.append("\n📊 EXAM PERFORMANCE\n")
    if exams:
        for e in exams[:5]:
            content.append(f"  • {e.exam_name}: {e.obtained_marks}/{e.total_marks} ({e.percentage:.1f}%)")
    else:
        content.append("  No exam records yet.")
    
    content.append("\n" + "-" * 60)
    
    # Problems
    content.append("\n🔍 FOCUS AREAS\n")
    for p in problems:
        content.append(f"  • {p.get('title', 'Issue')} [{p.get('category', 'General')}]")
    if custom_problem:
        content.append(f"  • {custom_problem} [Other]")
    
    content.append("\n" + "-" * 60)
    
    # Solution
    content.append("\n💡 RECOMMENDATIONS\n")
    content.append(solution)
    
    content.append("\n" + "=" * 60)
    content.append("Generated by MentorAI")
    content.append("=" * 60)
    
    # Write file
    with open(filepath, "w") as f:
        f.write("\n".join(content))
    
    print(f"[MentorAI] Report saved: {filepath}", flush=True)
    
    return filepath
