import os
import json
import re
import anthropic
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, max_retries=10)
CLAUDE_MODEL = "claude-sonnet-4-6"

def generate_ca_feedback(question_text: str, model_answer: str, student_answer: str, marks_total: float, marks_scored: float) -> dict:
    """
    Generate detailed feedback for a CA student's answer using Claude.
    """
    is_full_marks = marks_scored >= marks_total and marks_total > 0
    
    prompt = f"""
You are an expert CA examiner and mentor.
A student's answer has been checked by ICAI.
- QUESTION: {question_text}
- MODEL ANSWER (Correct Solution): {model_answer}
- STUDENT'S ACTUAL ANSWER: {student_answer}
- MARKS ALLOTTED TO THIS QUESTION: {marks_total}
- MARKS SCORED BY STUDENT: {marks_scored}

YOUR TASK:
Provide CRISP, CONCISE, and HUMAN-LIKE feedback explaining why they received {marks_scored} out of {marks_total} marks. Speak DIRECTLY to the student as their mentor (use "you / your" instead of "the student").

INSTRUCTIONS:
1. COMPARE your answer with the model answer.
2. {"Since you scored FULL MARKS, my feedback will be very positive, confirming exactly what you did right." if is_full_marks else "I will briefly identify exactly what you missed, got wrong, or poorly presented that led to the deduction of " + str(marks_total - marks_scored) + " marks."}
3. Keep the "what_went_right" and "what_went_wrong" sections crisp, conversational, and direct ("You correctly identified...", "You missed out on...").
4. **FOR CALCULATION-BASED QUESTIONS**: In the "what_went_wrong" section, focus on highlighting the **fundamental mistakes** (e.g., 'incorrect apportionment method', 'wrong unit conversion', 'failure to account for normal loss') but **DO NOT include specific numerical figures** from the calculation. Focus on the conceptual logic error rather than the arithmetic values.
5. CONCLUSION: Provide a 1-2 line encouraging conclusion summarizing your overall performance on this question.

OUTPUT FORMAT (JSON ONLY):
{{
  "marks_summary": "{marks_scored} / {marks_total}",
  "what_went_right": "...",
  "what_went_wrong": "...",
  "conclusion": "..."
}}
"""

    try:
        response = claude_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            system="You are an expert CA mentor. Provide detailed, professional feedback in JSON format.",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        
        text = response.content[0].text.strip()
        if text.startswith('```'):
            text = re.sub(r'^```json?\s*\n?', '', text)
            text = re.sub(r'\n?```\s*$', '', text)
            
        return json.loads(text)
        
    except Exception as e:
        print(f"[CA Feedback Generator] Error: {e}", flush=True)
        return {
            "error": str(e),
            "marks_summary": f"{marks_scored} / {marks_total}",
            "what_went_right": "Analysis skipped due to error.",
            "what_went_wrong": "Analysis failed.",
            "detailed_analysis": "Error during feedback generation.",
            "suggestion_for_improvement": "Check logs."
        }

def process_all_feedback(data, cache=None) -> dict:
    """
    Truly recursive explorer to find all leaf nodes that have been aligned and scored.
    cache: optional dict mapping question_text+student_answer to previous feedback
    """
    if cache is None: cache = {}
    
    if isinstance(data, list):
        return [process_all_feedback(item, cache) for item in data]
    
    if not isinstance(data, dict):
        return data

    # Check if this is a "question node" (has student_answer)
    if "student_answer" in data and ("marks_scored" in data or "marks" in data):
        m_scored = data.get("marks_scored")
        m_total = data.get("marks")
        s_ans = data.get("student_answer")
        q_text = data.get("question_text", data.get("question", ""))
        
        if s_ans and m_scored is not None:
            # Try to find in cache
            cache_key = f"{q_text}_{s_ans}_{m_scored}"
            if cache_key in cache:
                print(f"[CA Feedback] Reusing cached feedback for {data.get('question_id', 'Unknown')}")
                data["feedback"] = cache[cache_key]
            else:
                qid = data.get("question_id", "Unknown")
                print(f"[CA Feedback] Analyzing {qid}...", flush=True)
                
                feedback = generate_ca_feedback(
                    question_text=q_text,
                    model_answer=data.get("model_answer", ""),
                    student_answer=s_ans,
                    marks_total=float(m_total) if m_total is not None else 0.0,
                    marks_scored=float(m_scored)
                )
                data["feedback"] = feedback
                cache[cache_key] = feedback
            
    # Always recurse
    new_dict = {}
    for k, v in data.items():
        new_dict[k] = process_all_feedback(v, cache)
        
    return new_dict
