"""
Model Answer Builder Service

Extracts model answers from solution text for the entire question schema.
Creates a complete JSON schema with:
- question
- marks
- model_answer

This is a ONE-TIME operation. The output file is then used for grading.
"""

from app.core.openai_client import client
import json
import re


SYSTEM_PROMPT = """You are an expert CA examiner.

You will be given:
1. A JSON schema containing all questions from a CA exam
2. The complete solution text of the exam

Your task:
For EACH question in the schema, extract the correct model answer from the solution text.

Output the SAME JSON structure but transform each question entry to include:
{
  "question": "The original question text",
  "model_answer": "The complete answer from the solution text",
  "marks": <marks for this question as integer, default 5 if not specified>
}

RULES:
- Keep the EXACT same JSON structure (sections, question numbers, subparts)
- Extract model answers EXACTLY as written in the solution
- For MCQs, extract the correct option letter AND answer (e.g., "(a) Resident but not ordinarily resident")
- Include calculation steps if present in solution
- If answer not found for a question, use empty string "" for model_answer
- marks should be integer
- Return ONLY valid JSON, no markdown, no explanations"""


def build_model_answers(question_schema: dict, solution_text: str) -> dict:
    """
    Build complete model answers schema from questions and solution text.
    
    Args:
        question_schema: Original question schema with just questions
        solution_text: Full solution text from the PDF
    
    Returns:
        Enhanced schema with model_answer and marks for each question
    """
    
    # Truncate solution text if too long (API limit)
    max_solution_chars = 100000  # ~25k tokens
    if len(solution_text) > max_solution_chars:
        # Take first and last parts to cover most content
        half = max_solution_chars // 2
        solution_text = solution_text[:half] + "\n\n... [truncated] ...\n\n" + solution_text[-half:]
    
    prompt = f"""
Question Schema (transform this structure):
{json.dumps(question_schema, indent=2)}

Solution Text (extract answers from here):
{solution_text}

Transform the question schema by adding model_answer and marks to each question.
Return the complete transformed JSON.
"""

    print("[ModelAnswerBuilder] Sending request to extract all model answers...", flush=True)
    
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1
    )
    
    content = response.choices[0].message.content.strip()
    
    # Clean markdown code blocks if present
    if content.startswith("```"):
        content = re.sub(r'^```json?\n?', '', content)
        content = re.sub(r'\n?```$', '', content)
    
    print("[ModelAnswerBuilder] Parsing response...", flush=True)
    
    try:
        result = json.loads(content)
        print("[ModelAnswerBuilder] Successfully extracted model answers!", flush=True)
        return result
    except json.JSONDecodeError as e:
        print(f"[ModelAnswerBuilder] JSON parse error: {e}", flush=True)
        raise RuntimeError(f"Failed to parse model answer JSON from LLM: {e}")
