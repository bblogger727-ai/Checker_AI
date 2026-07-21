import os
import json
import re
import time
import anthropic
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
CLAUDE_MODEL = "claude-sonnet-4-6"

def fix_json_output(raw: str) -> str:
    """Strip markdown code fences and fix common issues."""
    text = raw.strip()
    if text.startswith('```'):
        text = re.sub(r'^```json?\s*\n?', '', text)
        text = re.sub(r'\n?```\s*$', '', text)
    return text

def split_into_chunks(text: str, max_chars: int = 10000, overlap: int = 2000) -> list:
    """Split text into manageable chunks with overlap to avoid splitting questions."""
    chunks = []
    if len(text) <= max_chars:
        return [text]
        
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks

def build_questions_schema(solution_text: str) -> dict:
    """
    STEP 1: Extract ONLY the question structure (no model answers).
    Returns a FLAT schema dict: { "Q1a": { "question_id": "...", ... }, "Q1b": ... }
    Rule: Merge sub-subparts like (i), (ii) into the root subpart (a, b) if they belong together.
    Strictly EXCLUDE MCQs.
    """
    if len(solution_text) <= 12000:
        return _extract_questions_from_chunk(solution_text)

    chunks = split_into_chunks(solution_text)
    merged_schema = {}

    for i, chunk in enumerate(chunks):
        print(f"[CA Schema Builder] Processing chunk {i+1}/{len(chunks)}...", flush=True)
        chunk_schema = _extract_questions_from_chunk(chunk, chunk_num=i+1, total_chunks=len(chunks))
        # Since it's flat, just update
        merged_schema.update(chunk_schema)
        if i < len(chunks) - 1:
            time.sleep(1)

    return merged_schema

def _extract_questions_from_chunk(chunk_text: str, chunk_num: int = 1, total_chunks: int = 1) -> dict:
    """Extract ONLY question structure (no answers) from a chunk."""
    prompt = f"""
You are an expert CA examiner. You are given PART {chunk_num}/{total_chunks} of a MODEL ANSWER SHEET.

Your task is to extract the QUESTION STRUCTURE ONLY for every DESCRIPTIVE question in this document.

CRITICAL RULES:
1. **FLAT OUTPUT**: Return a single flat JSON object where keys are the question labels (e.g., "Q1a", "Q5c", "Q2.6"). DO NOT nest questions under Case Scenarios or Sections.
2. **STRICT MCQ EXCLUSION**: DO NOT extract any Multiple Choice Questions. MCQs are identifiable by 4 lettered options (a/b/c/d), "Choose the correct option", or answers starting with "Option (A)", "Option (B)", etc. If an entire section consists of MCQs, SKIP IT ENTIRELY.
3. **SUBPARTS / DECIMALS**: Questions may be labeled with letters (e.g., 1(a), 1(b)) or decimals (e.g., 2.6, 3.7). Extract these as separate entries (e.g., "Q1a", "Q1b", "Q2.6", "Q3.7"). For decimal questions, set `subpart` to an empty string.
4. **MERGE SUB-SUBPARTS**: If a subpart like "Q1a" has internal points like "(i)" and "(ii)", MERGE them into the single "Q1a" entry. Combine their text and add their marks.
5. **MARKS**: Find the total marks (e.g., "(5 Marks)") at the end of the question text. If missing, look at the end of the subpart.
6. **IDs**: question_id should be the same as the key (e.g. "Q1a", "Q2.6").

For each descriptive question extract:
   - question_id: (e.g. "Q1a" or "Q2.6")
   - question_number: (e.g. "Q1" or "Q2.6")
   - subpart: (e.g. "a", or "" for decimals)
   - question_text: (the full text of the question)
   - marks: (total marks for this entry)
   - model_answer: "" (always empty)

OUTPUT FORMAT: A flat JSON object.
Example:
{{
  "Q1a": {{
    "question_id": "Q1a",
    "question_number": "Q1",
    "subpart": "a",
    "question_text": "...",
    "marks": 5,
    "model_answer": ""
  }},
  "Q2.6": {{
    "question_id": "Q2.6",
    "question_number": "Q2.6",
    "subpart": "",
    "question_text": "...",
    "marks": 4,
    "model_answer": ""
  }}
}}

---
MODEL ANSWER SHEET TEXT (PART {chunk_num}/{total_chunks}):
{chunk_text}
"""
    try:
        response = claude_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8192,
            system="You are a strict JSON extraction assistant. Output ONLY valid JSON. No prose.",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        return json.loads(fix_json_output(response.content[0].text.strip()))
    except Exception as e:
        print(f"[CA Schema Builder] Error in chunk {chunk_num}: {e}")
        return {}


# ─── Legacy combined function (kept for backward compatibility) ───────────────

def build_ca_schema_and_answers(solution_text: str) -> dict:
    """
    LEGACY: Extract structure AND model answers in a single Claude call.
    Kept for backward compatibility. New pipeline uses build_questions_schema()
    followed by build_model_answers_claude().
    """
    if len(solution_text) <= 12000:
        return _extract_from_chunk(solution_text)

    chunks = split_into_chunks(solution_text)
    merged_schema = {}

    for i, chunk in enumerate(chunks):
        print(f"[CA Schema Builder] Processing chunk {i+1}/{len(chunks)}...", flush=True)
        chunk_schema = _extract_from_chunk(chunk, chunk_num=i+1, total_chunks=len(chunks))
        _merge_dicts(merged_schema, chunk_schema)
        if i < len(chunks) - 1:
            time.sleep(1)

    return merged_schema

def _extract_from_chunk(chunk_text: str, chunk_num: int = 1, total_chunks: int = 1) -> dict:
    prompt = f"""
You are an expert CA examiner. You are given PART {chunk_num}/{total_chunks} of a MODEL ANSWER SHEET.
This document contains both the questions and their corresponding model answers.

Your task is to extract the question schema and the model answers for the DESCRIPTIVE QUESTIONS ONLY.

SPECIFIC TARGETS:
1. Extract ALL descriptive (written) questions and their corresponding model answers.
2. DO NOT extract any MCQ questions (Multiple Choice Questions) or MCQ sections.
   MCQs are identifiable by 4 lettered options (a/b/c/d) or "Select the correct option" type phrasing.

For each matching question/subquestion extract:
- question_id (unique: <Section>-Q<Num> e.g., SectionB-Q1a)
- question_number (the root question number, e.g. "Q1")
- subpart (the subpart number/label, e.g. "a", "b"; null if none)
- question_text (the actual descriptive question being asked)
- marks (CRITICAL: Find the marks allotted. Look for [X] marks, (X) marks, or just X marks near the question text. DO NOT return null if marks are visible.)
- model_answer (the COMPLETE model answer/solution provided in the document)

CRITICAL RULES:
1. EXTRACT EVERYTHING: Do not summarize the model answer. Include tables, calculations, and working notes.
2. OUTPUT FORMAT: Return a structured JSON object organized by Sections.

---
MODEL ANSWER SHEET TEXT (PART {chunk_num}):
{chunk_text}
"""
    try:
        response = claude_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8192,
            system="You are a strict JSON extraction assistant. Output ONLY valid JSON. No prose.",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        return json.loads(fix_json_output(response.content[0].text.strip()))
    except Exception as e:
        print(f"[CA Schema Builder] Error in chunk {chunk_num}: {e}")
        return {}

def _merge_dicts(master, extra):
    """Recursively merge two dictionaries."""
    for key, value in extra.items():
        if key in master and isinstance(master[key], dict) and isinstance(value, dict):
            _merge_dicts(master[key], value)
        else:
            master[key] = value
