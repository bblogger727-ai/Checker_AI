from app.core.openai_client import client
import json


def build_solution_schema(solution_text: str) -> dict:
    prompt = f"""
YYou are given the text of a CA exam solution document (typed).

Your task is to extract ONLY the question paper structure.

You must:

1. Detect Sections (Section A, Section B, etc.)
2. Inside each section detect:
   - MCQ block (if present)
   - Descriptive questions (Q1, Q2, ...)
3. For every question and subquestion extract:

   - question_id (unique string)
   - question_number (Q1, Q2, etc. OR MCQ number)
   - subpart (a, b, i, ii or null)
   - full question text ONLY
   - marks (integer)

---
Return this exact structure:

{{
  "SectionA": {{
    "MCQ": {{
      "1": {{
      "question_id": "A-MCQ-1",
        "question_number": "1",
        "subpart": null,
        "question": "...",
        "marks": 1
    }},
    "Q1": {{
       "a": {{
        "question_id": "A-Q1-a",
        "question_number": "Q1",
        "subpart": "a",
        "question": "...",
        "marks": 15
      }}
    }},
    "Q2": {{
      "a": {{
        "question_id": "A-Q2-a",
        "question_number": "Q2",
        "subpart": "a",
        "question": "...",
        "marks": 5
      }},
      "b": {{
        "i": {{
          "question_id": "A-Q2-b-i",
          "question_number": "Q2",
          "subpart": "b(i)",
          "question": "...",
          "marks": 5
      }}
    }}
  }},
  "SectionB": {{
    ...
  }}
}}

### Rules (MANDATORY)

- Extract ONLY the question statements.
- DO NOT include any answers or solution content.
- DO NOT summarize.
- Preserve original numbering.
- Marks must be integer.
- Use empty string "" if marks are not explicitly stated.
- Maintain hierarchy exactly.
- question_id must be deterministic and unique using this format:

  <SectionLetter>-Q<Number>-<subparts>

  Examples:
  - A-MCQ-1
  - A-Q1-a
  - B-Q3-b-ii

- Output ONLY valid JSON.
- No markdown.
- No explanations.
- No extra text.

---

Solution text:
--------------------
{solution_text}
"""

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": "You are a strict JSON generator for exam question schemas."},
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    output = response.choices[0].message.content.strip()

    try:
        return json.loads(output)
    except Exception:
        raise ValueError(f"Invalid JSON returned by model:\n{output}")
