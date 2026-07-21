"""
generate_student_report.py
──────────────────────────
Stage 8: Generate a student-facing performance report (.txt) from grading_final.json.

Output file: <dataset_dir>/student_report.txt

Label format matches teacher style:
  Presentation is [X]
  Concepts - [X]
  Overall Performance - [X]
  Strength is - [You ...]
  Weakness is - [Lack of ...]

Voice: second person ("You effectively..." not "The student...")
"""

from __future__ import annotations

import json
import os
import re

# Load .env so OPENAI_API_KEY is available in all execution contexts
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ── LLM call ─────────────────────────────────────────────────────────────────

def _call_llm(prompt: str, max_tokens: int = 400) -> str | None:
    try:
        import openai
        client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.4,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"  ⚠ LLM call failed: {e}")
        return None


# ── Aggregate grading data ────────────────────────────────────────────────────

def _analyse_grading(grading_data: dict) -> dict:
    """
    Aggregate marks and feedback from graded_answers.

    Handles two nesting levels:
      - Flat  (SectionA):  graded["SectionA"]["MCQ"]["1"] = { marks_obtained, ... }
      - Nested (SectionB): graded["SectionB"]["Q1"]["Q1a"] = { marks_obtained, ... }

    Both structures have the actual graded entry (with marks_obtained) at the
    innermost dict that contains the "marks_obtained" key.
    """
    graded = grading_data.get("graded_answers", {})
    total_obtained = 0.0
    total_possible = 0.0
    tiers:        list[str] = []
    correct_items: list[str] = []
    missed_items:  list[str] = []
    errors_items:  list[str] = []
    feedbacks:     list[str] = []

    def _process_entry(q_id: str, entry: dict) -> None:
        """Process a single graded sub-question entry."""
        nonlocal total_obtained, total_possible
        obtained = float(entry.get("marks_obtained", 0) or 0)
        possible = float(entry.get("marks_total",    0) or entry.get("marks", 0) or 0)
        total_obtained += obtained
        total_possible += possible
        tier = entry.get("tier", "")
        if tier:
            tiers.append(tier)
        fb = entry.get("feedback", "") or ""
        if fb:
            feedbacks.append(f"{q_id}: {fb}")
        for item in (entry.get("correct_items") or []):
            correct_items.append(str(item))
        for item in (entry.get("key_points_missed") or []):
            missed_items.append(str(item))
        for item in (entry.get("major_errors") or []):
            errors_items.append(str(item))

    for section, questions in graded.items():
        if not isinstance(questions, dict):
            continue
        for q_id, entry in questions.items():
            if not isinstance(entry, dict):
                continue
            # If this entry has marks_obtained it IS a graded result (flat, e.g. MCQ)
            if "marks_obtained" in entry:
                _process_entry(q_id, entry)
            else:
                # It's a parent question (e.g. SectionB Q1) — iterate its sub-questions
                for sub_id, sub_entry in entry.items():
                    if isinstance(sub_entry, dict) and "marks_obtained" in sub_entry:
                        _process_entry(sub_id, sub_entry)

    # If total_possible is still 0, fall back to reading from metadata
    if total_possible == 0.0:
        meta = grading_data.get("metadata", {})
        total_obtained = float(meta.get("total_marks_obtained", 0) or 0)
        total_possible = float(meta.get("total_marks_possible", 0) or 0)

    pct = (total_obtained / total_possible * 100) if total_possible else 0
    return {
        "total_obtained": total_obtained,
        "total_possible": total_possible,
        "pct":            round(pct, 1),
        "tiers":          tiers,
        "correct_items":  correct_items[:8],
        "missed_items":   missed_items[:6],
        "errors_items":   errors_items[:6],
        "feedbacks":      feedbacks[:8],
    }



# ── LLM report generation ────────────────────────────────────────────────────

def _generate_report_data(metrics: dict, dataset_id: str) -> dict:
    """
    Ask GPT-4o-mini for all report fields in one structured JSON call.
    Exact label format and second-person voice are enforced via the prompt.
    """
    correct_str  = "\n".join(f"  - {c}" for c in metrics["correct_items"]) or "  (none recorded)"
    missed_str   = "\n".join(f"  - {m}" for m in metrics["missed_items"])  or "  (none recorded)"
    errors_str   = "\n".join(f"  - {e}" for e in metrics["errors_items"])  or "  (none recorded)"
    feedback_str = "\n".join(metrics["feedbacks"]) or "(none)"
    tier_summary = ", ".join(metrics["tiers"]) or "mixed"

    prompt = f"""You are a CA exam teacher writing a concise student performance card.

Paper: {dataset_id}
Marks: {metrics['total_obtained']}/{metrics['total_possible']} ({metrics['pct']}%)
Question tiers: {tier_summary}

What the student did well:
{correct_str}

Points missed / key errors:
{missed_str}
{errors_str}

Per-question grader notes:
{feedback_str}

Produce a JSON object with EXACTLY these keys:
{{
  "presentation":        "<short phrase only — e.g. 'Neat and Well-structured'>",
  "concepts":            "<short phrase only — e.g. 'Strong conceptual clarity'>",
  "overall_performance": "<one short sentence — no 'The student' prefix, just the observation>",
  "strength":            "<one short sentence starting with 'You' — e.g. 'You effectively identified...'>",
  "weakness":            "<one short noun phrase or sentence — e.g. 'Lack of specificity in technical details'>",
  "concept_clarity_rating": <integer 1-5>,
  "language_rating":        <integer 1-5>,
  "presentation_rating":    <integer 1-5>,
  "teacher_feedback": "<2-3 sentences addressed directly to the student using 'you/your', constructive and specific>"
}}

IMPORTANT rules:
- "presentation" and "concepts": short descriptive phrases only (3-6 words), NO full sentences.
- "overall_performance": a plain observation, do NOT start with 'The student'.
- "strength": MUST start with 'You' (second person).
- "weakness": a noun phrase or short sentence, NOT 'The student's weakness is...'.
- "teacher_feedback": use 'you/your' throughout, never 'the student'.
- NEVER mention OCR, system errors, handwriting recognition issues, or anything related to the technical pipeline. Always frame feedback purely around the student's conceptual knowledge and presentation.
- Return ONLY the JSON. No markdown fences. No extra text."""

    raw = _call_llm(prompt, max_tokens=500)
    if not raw:
        return _fallback_report_data(metrics)

    # Strip markdown fences if the model adds them anyway
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$",           "", raw.strip())

    try:
        data = json.loads(raw)
        required = [
            "presentation", "concepts", "overall_performance",
            "strength", "weakness",
            "concept_clarity_rating", "language_rating", "presentation_rating",
            "teacher_feedback",
        ]
        for k in required:
            if k not in data:
                raise ValueError(f"Missing key: {k}")
        for rk in ("concept_clarity_rating", "language_rating", "presentation_rating"):
            data[rk] = max(1, min(5, int(data[rk])))
        return data
    except Exception as e:
        print(f"  ⚠ JSON parse failed ({e}), using fallback.")
        return _fallback_report_data(metrics)


def _fallback_report_data(metrics: dict) -> dict:
    pct = metrics["pct"]
    rating = 5 if pct >= 85 else (4 if pct >= 70 else (3 if pct >= 50 else 2))
    return {
        "presentation":        "Adequate",
        "concepts":            "Moderate understanding demonstrated",
        "overall_performance": f"Scored {metrics['total_obtained']}/{metrics['total_possible']} ({pct}%) with mixed performance",
        "strength":            "You attempted most questions with reasonable effort",
        "weakness":            "Key points missed in several answers",
        "concept_clarity_rating":  rating,
        "language_rating":         rating,
        "presentation_rating":     rating,
        "teacher_feedback": (
            f"You scored {metrics['total_obtained']}/{metrics['total_possible']} ({pct}%) on this paper. "
            "You demonstrate a reasonable understanding of the subject matter. "
            "Focus on completeness of answers, working notes, and revisiting missed concepts."
        ),
    }


# ── Stars helper ──────────────────────────────────────────────────────────────

def _stars(rating: int, out_of: int = 5) -> str:
    return "★" * rating + "☆" * (out_of - rating) + f"  ({rating}/{out_of})"


# ── TXT builder ───────────────────────────────────────────────────────────────

def _build_txt(report: dict, metrics: dict, dataset_id: str, output_path: str):
    """Write the report as a plain text file matching the teacher's label style."""

    lines = []

    # Header
    lines += [
        f"STUDENT PERFORMANCE REPORT",
        f"Paper: {dataset_id}   |   Marks: {metrics['total_obtained']}/{metrics['total_possible']} ({metrics['pct']}%)",
        "=" * 58,
        "",
    ]

    # Performance metrics — exact label format
    lines += [
        f"Presentation is {report['presentation']}",
        f"Concepts - {report['concepts']}",
        f"Overall Performance - {report['overall_performance']}",
        f"Strength is - {report['strength']}",
        f"Weakness is - {report['weakness']}",
        "",
    ]

    # Ratings
    lines += [
        "-" * 58,
        "RATINGS (out of 5)",
        "-" * 58,
        f"Concept Clarity         {_stars(report['concept_clarity_rating'])}",
        f"Language & Working Notes {_stars(report['language_rating'])}",
        f"Presentation            {_stars(report['presentation_rating'])}",
        "",
    ]

    # Teacher feedback
    lines += [
        "-" * 58,
        "FEEDBACK",
        "-" * 58,
        report["teacher_feedback"],
        "",
        "─" * 58,
        "Generated by CheckerAI",
    ]

    content = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  ✓ Student report → {output_path}")


# ── Public entry point ────────────────────────────────────────────────────────

def generate_student_report(grading_json_path: str, dataset_dir: str, dataset_id: str):
    """
    Main entry point called from the pipeline.

    Args:
        grading_json_path: Path to grading_final.json
        dataset_dir:       Dataset output directory (report saved here)
        dataset_id:        Human-readable paper ID (e.g. '2115')
    """
    print("\n" + "=" * 60)
    print("STAGE 8: Student Performance Report (TXT)")
    print("=" * 60)

    with open(grading_json_path, "r") as f:
        grading_data = json.load(f)

    metrics = _analyse_grading(grading_data)
    print(f"  Marks: {metrics['total_obtained']}/{metrics['total_possible']} ({metrics['pct']}%)")
    print(f"  Generating report via LLM (gpt-4o-mini)...")

    report = _generate_report_data(metrics, dataset_id)

    output_path = os.path.join(dataset_dir, "student_report.txt")
    _build_txt(report, metrics, dataset_id, output_path)

    return output_path


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4:
        print("Usage: python generate_student_report.py <grading_final.json> <dataset_dir> <dataset_id>")
        sys.exit(1)
    generate_student_report(sys.argv[1], sys.argv[2], sys.argv[3])
