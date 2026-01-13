from app.core.openai_client import client
import json


def align_answers_to_schema(student_pages: list, schema: dict) -> dict:
    student_text = "\n\n".join(
        [f"[Page {p['page']}]\n{p['text']}" for p in student_pages]
    )

    prompt = f"""
You are given:

1) Official exam question schema (JSON)
2) Student answer OCR text

Your task:

For EACH question & subquestion in the schema:
- Find the corresponding student answer
- Extract ONLY the student answer text
- If missing, return empty string ""

Return the SAME JSON structure but add:

"student_answer": "..."

Do NOT change question text or marks.

Return valid JSON only.

Schema:
{json.dumps(schema, indent=2)}

Student OCR text:
-----------------
{student_text}
"""

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": "You align student answers to official exam schema and output strict JSON."},
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    output = response.choices[0].message.content.strip()

    try:
        return json.loads(output)
    except Exception:
        raise ValueError("Invalid JSON returned from alignment model.")
