from app.core.openai_client import client


def parse_answers(raw_pages: list) -> dict:
    combined_text = "\n\n".join(
        [f"Page {p['page']}:\n{p['text']}" for p in raw_pages]
    )

    prompt = f"""
You are given OCR extracted text from a student's handwritten answer sheet.

Your task:
1. Identify question numbers (Q1, Q2, Q3a, etc.)
2. Group the answers correctly.
3. Fix minor OCR errors.
4. Return ONLY valid JSON.

Format strictly:

{{
  "Q1": "answer text",
  "Q2": "answer text"
}}

Text:
----------------
{combined_text}
"""

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": "You are a strict JSON generator."},
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    content = response.choices[0].message.content

    try:
        return eval(content)
    except Exception:
        raise ValueError("Failed to parse structured answers from LLM output")
