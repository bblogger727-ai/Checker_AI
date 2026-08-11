"""
Mismatch Detector — Stage 5.5 of the grading pipeline.

Scans grading_final.json for questions that scored <= 0.5 marks,
then uses GPT-4o-mini to check whether the feedback indicates the
student answered a completely different question (wrong-paper scenario).

Returns a list of question labels that are flagged as potential
paper-version mismatches, e.g. ["Q2a", "Q3b"].
"""

import json
import os

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# ── OpenAI lazy client ────────────────────────────────────────────────────────

_client: OpenAI | None = None


def _get_openai_client() -> OpenAI:
    global _client
    if _client is not None:
        return _client
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set in environment.")
    _client = OpenAI(api_key=api_key)
    return _client


# ── Prompt ────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are an exam quality-control assistant. You will be given a list of questions that received very low marks (0 or 0.5 out of their maximum), along with the feedback the grader wrote for each one.

Your task: decide whether the grader's feedback indicates that the STUDENT ANSWERED A COMPLETELY DIFFERENT QUESTION than the one they were supposed to answer. This typically looks like:
- "Student has answered a question about X but this question is about Y"
- "The student appears to have answered a different topic/question"
- "Answer does not match the question asked at all"
- "Student answered [other topic] instead of [required topic]"
- Feedback that describes a completely unrelated topic from what the question asks

Do NOT flag a question if:
- The student simply got the answer wrong, used the wrong formula, or made calculation errors
- The student answered the correct topic but missed key points
- The student gave an incomplete or poor answer to the correct question

Respond with a JSON object in this exact format:
{
  "flagged": ["Q1a", "Q3b"]
}

If no questions are flagged, return:
{
  "flagged": []
}

Only include question labels where you are confident the feedback indicates a wrong-question scenario."""

_USER_TEMPLATE = """Below are low-mark questions from this exam paper. For each one, the question label and the grader's feedback are shown.

{entries}

Which of these questions have feedback suggesting the student answered a completely different question than asked? Return only their labels in the JSON format specified."""


def _collect_low_mark_questions(grading_final: dict, threshold: float = 0.5) -> list[dict]:
    """Walk grading_final['graded_answers'] and collect all sub-questions with marks_obtained <= threshold."""
    low_qs = []
    graded = grading_final.get("graded_answers", {})

    for section_key, section_val in graded.items():
        if section_key == "paper_meta":
            continue
        if not isinstance(section_val, dict):
            continue

        for q_key, q_val in section_val.items():
            if not isinstance(q_val, dict):
                continue

            # Could be a direct question (Q1a level) or a wrapper with sub-questions
            # Check if this dict itself has marks_obtained (leaf node)
            if "marks_obtained" in q_val:
                mo = q_val.get("marks_obtained")
                feedback = q_val.get("feedback", "")
                if mo is not None and float(mo) <= threshold and feedback:
                    low_qs.append({"label": q_key, "feedback": feedback, "marks": float(mo)})
            else:
                # Wrapper: iterate its children
                for sq_key, sq_val in q_val.items():
                    if not isinstance(sq_val, dict):
                        continue
                    mo = sq_val.get("marks_obtained")
                    feedback = sq_val.get("feedback", "")
                    if mo is not None and float(mo) <= threshold and feedback:
                        low_qs.append({"label": sq_key, "feedback": feedback, "marks": float(mo)})

    return low_qs


def detect_question_mismatches(grading_final_path: str, threshold: float = 0.5) -> list[str]:
    """
    Main entry point. Reads grading_final.json, finds questions with marks <= threshold,
    calls GPT-4o-mini to detect wrong-paper feedback, returns flagged question labels.

    Returns an empty list if no mismatches are detected or if the API call fails.
    """
    try:
        with open(grading_final_path, "r", encoding="utf-8") as f:
            grading_final = json.load(f)
    except Exception as e:
        print(f"[MismatchDetector] Could not read {grading_final_path}: {e}")
        return []

    low_qs = _collect_low_mark_questions(grading_final, threshold=threshold)
    if not low_qs:
        print("[MismatchDetector] No low-mark questions found — skipping mismatch check.")
        return []

    print(f"[MismatchDetector] Checking {len(low_qs)} low-mark question(s) for paper mismatch...")

    # Format the entries for the prompt
    entries_text = "\n\n".join(
        f"Question {q['label']} ({q['marks']} marks):\nFeedback: {q['feedback']}"
        for q in low_qs
    )
    user_message = _USER_TEMPLATE.format(entries=entries_text)

    try:
        client = _get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.0,
            max_tokens=256,
        )
        raw = response.choices[0].message.content
        result = json.loads(raw)
        flagged = result.get("flagged", [])
        if flagged:
            print(f"[MismatchDetector] ⚠️  Flagged questions: {flagged}")
        else:
            print("[MismatchDetector] ✓ No paper mismatch detected.")
        return flagged
    except Exception as e:
        print(f"[MismatchDetector] GPT-4o-mini call failed (skipping): {e}")
        return []
