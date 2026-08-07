from app.core.openai_client import client
import json
import re
import time


# Maximum chars per chunk (~12k tokens to stay well under 30k TPM limit)
MAX_CHUNK_CHARS = 10000


def fix_json_output(raw: str) -> str:
    """
    Fix common GPT JSON output issues:
    1. Strip markdown code fences (```json ... ```)
    2. Replace unquoted null keys (null:) with quoted ("null":)
    """
    # Strip markdown code fences
    text = raw.strip()
    if text.startswith('```'):
        text = re.sub(r'^```json?\s*\n?', '', text)
        text = re.sub(r'\n?```\s*$', '', text)
    # Replace unquoted null keys: `null:` -> `"null":`
    text = re.sub(r'(?<=\{|,)\s*null\s*:', ' "null":', text)
    return text


def split_into_chunks(solution_text: str) -> list:
    """
    Split solution text into manageable chunks by page markers.
    Each chunk stays under MAX_CHUNK_CHARS.
    """
    # Split by page markers (supports both standard and PyMuPDF formats)
    page_pattern = r'(========== PAGE \d+ ==========|=== Page \d+ ===)'
    parts = re.split(page_pattern, solution_text, flags=re.IGNORECASE)
    
    # Reconstruct pages with their content
    pages = []
    current_page_header = ""
    
    for i, part in enumerate(parts):
        if re.match(page_pattern, part):
            current_page_header = part
        elif part.strip():
            pages.append(current_page_header + "\n" + part)
    
    # If no page markers, split by character count
    if len(pages) <= 1:
        chunks = []
        for i in range(0, len(solution_text), MAX_CHUNK_CHARS - 5000):
            chunk = solution_text[i:i + MAX_CHUNK_CHARS - 5000]
            chunks.append(chunk)
        return chunks
    
    # Group pages into chunks that fit under MAX_CHUNK_CHARS
    chunks = []
    current_chunk = ""
    
    for page in pages:
        # If a single page is huge, we must split it
        if len(page) > MAX_CHUNK_CHARS:
             # First, save current accumulated chunk if any
             if current_chunk:
                 chunks.append(current_chunk)
                 current_chunk = ""
             
             # Split the huge page into smaller parts
             for i in range(0, len(page), MAX_CHUNK_CHARS):
                 chunks.append(page[i:i + MAX_CHUNK_CHARS])
             continue
        
        if len(current_chunk) + len(page) > MAX_CHUNK_CHARS:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = page
        else:
            current_chunk += "\n\n" + page if current_chunk else page
    
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks


import anthropic
import os
from dotenv import load_dotenv

load_dotenv()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
CLAUDE_MODEL = "claude-sonnet-4-6"

def extract_schema_from_chunk(chunk_text: str, chunk_num: int, total_chunks: int) -> dict:
    """Extract question schema from a single chunk of text."""
    
    prompt = f"""
You are given PART {chunk_num}/{total_chunks} of a CA exam solution document.

Your task is to extract the question paper structure from THIS CHUNK ONLY.

Extract:
1. Sections (Section A, Section B, etc.) if present in this chunk
2. MCQ blocks if present
3. Descriptive questions (Q1, Q2, etc.) if present

For each question/subquestion extract:
- question_id (unique: <Section>-Q<Num><subpart> e.g., SectionB-Q1a)
- question_number (the root question number, e.g. "Q1")
- subpart (the subpart letter e.g. "a", "b", "c", or null if none)
- full question text
- marks (MUST be a number/float for this subpart).
- or_group (for OR alternatives, otherwise null)

CRITICAL RULES FOR SUBQUESTIONS:
1. For DESCRIPTIVE questions (non-MCQ), if a question has subparts (a, b, c or i, ii, iii), extract each subpart (a, b, c) as a SEPARATE subquestion entry (e.g., Q1a, Q1b, Q1c).
2. DO NOT consolidate subparts (a, b, c) into a single parent entry. Each subpart (a, b, c) MUST be listed individually under its parent question object (e.g., "Q1": {{ "Q1a": {{...}}, "Q1b": {{...}}, "Q1c": {{...}} }}).
3. The `question_text` MUST contain the exact text for that specific subpart.
4. The `marks` MUST be the marks for that specific subpart (e.g., 5, 4, 6). Pay close attention to marks indicated next to each subpart.
5. PREVENT MISLABELING: Read question numbers carefully. If a question starts with "Question 2(a)", set question_number="Q2", subpart="a", key="Q2a".

Example format for descriptive question with subparts:
{{
  "SectionB": {{
    "Q1": {{
      "Q1a": {{ "question_id": "SectionB-Q1a", "question_number": "Q1", "subpart": "a", "question_text": "...", "marks": 5, "or_group": null }},
      "Q1b": {{ "question_id": "SectionB-Q1b", "question_number": "Q1", "subpart": "b", "question_text": "...", "marks": 4, "or_group": null }},
      "Q1c": {{ "question_id": "SectionB-Q1c", "question_number": "Q1", "subpart": "c", "question_text": "...", "marks": 5, "or_group": null }}
    }}
  }}
}}

Exception: MCQ questions should be listed individually under their MCQ block.

Return JSON structure:
{{
  "SectionA": {{
    "MCQ": {{ "1": {{"question_id": "A-MCQ-1", "marks": 1, ...}} }}
  }},
  "SectionB": {{
    "Q1": {{
      "Q1a": {{ "question_id": "SectionB-Q1a", "marks": 5, "subpart": "a", ... }}
    }}
  }}
}}

RULES:
- Extract ONLY questions from this chunk
- If chunk has no new questions, return {{}}
- Output ONLY valid JSON, no markdown

---
Chunk text:
{chunk_text}
"""
    
    for attempt in range(2):
        try:
            print(f"[Schema Builder]   Attempt {attempt+1} for chunk {chunk_num}...", flush=True)
            
            # On retry, be more explicit about JSON structure
            current_system = "You are a strict JSON generator for exam question schemas. Output only valid JSON. Do not include markdown fences."
            if attempt > 0:
                current_system += " If no questions are found, you MUST return an empty object {}."

            response = claude_client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=current_system,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0 if attempt == 0 else 0.1
            )
            
            output = response.content[0].text.strip()
            
            if not output:
                print(f"[Schema Builder]   Warning: Empty response from Claude on attempt {attempt+1}.", flush=True)
                continue

            # Fix null keys and markdown fences
            output = fix_json_output(output)
            
            return json.loads(output)
            
        except Exception as e:
            print(f"[Schema Builder]   Attempt {attempt+1} failed: {e}", flush=True)
            if attempt == 0:
                time.sleep(2)
            else:
                return {}
    
    return {}


def merge_schemas(schemas: list) -> dict:
    """
    Merge multiple chunk schemas into one complete schema.
    Normalizes 'Division' -> 'Section' and consolidates MCQs.
    """
    merged = {}
    
    def normalize_key(k):
        if not k: return k
        # Standardize Section names
        k = k.replace(" ", "")
        if "Division" in k:
            k = k.replace("Division", "Section")
        return k

    for schema in schemas:
        if not isinstance(schema, dict):
            continue
            
        # First, handle top-level MCQ if it exists
        if "MCQ" in schema:
            mcq_content = schema.pop("MCQ")
            if isinstance(mcq_content, dict):
                if "SectionA" not in merged:
                    merged["SectionA"] = {}
                if "MCQ" not in merged["SectionA"]:
                    merged["SectionA"]["MCQ"] = {}
                merged["SectionA"]["MCQ"].update(mcq_content)

        # Handle other top-level questions that might have been returned by Claude
        # If Claude returns {"Q1": {...}} instead of {"SectionB": {"Q1": {...}}}
        for key in list(schema.keys()):
            if re.match(r'^[AQ]\d+', key) or key == "MCQ":
                # This looks like a question at the top level. Try to find its section.
                # Heuristic: Section A for MCQ, Section B for Q1 if unspecified.
                target_section = "SectionA" if "MCQ" in key else "SectionB"
                if target_section not in merged:
                    merged[target_section] = {}
                
                content = schema.pop(key)
                if isinstance(content, dict):
                    if key not in merged[target_section]:
                        merged[target_section][key] = {}
                    merged[target_section][key].update(content)

        # Process remaining sections
        for section_key, section_content in schema.items():
            if not isinstance(section_content, dict):
                continue
            
            norm_section = normalize_key(section_key)
            if norm_section not in merged:
                merged[norm_section] = {}
            
            for question_key, question_content in section_content.items():
                if question_key in ["null", "", None]:
                    continue
                
                if question_key == "MCQ":
                    if "MCQ" not in merged[norm_section]:
                        merged[norm_section]["MCQ"] = {}
                    if isinstance(question_content, dict):
                        merged[norm_section]["MCQ"].update(question_content)
                else:
                    if not isinstance(question_content, dict):
                        continue
                        
                    # Locate if this question already exists in ANY section
                    existing_sec = None
                    for sec in merged.keys():
                        if question_key in merged[sec]:
                            existing_sec = sec
                            break
                    
                    if existing_sec:
                        target_sec = existing_sec
                        existing_q = merged[target_sec][question_key]
                        
                        if "question_id" in question_content:
                            if "question_id" in existing_q:
                                new_text = question_content.get("question_text", "")
                                old_text = existing_q.get("question_text", "")
                                if new_text and old_text and new_text not in old_text:
                                    existing_q["question_text"] = old_text + "\n" + new_text
                                elif new_text and not old_text:
                                    existing_q["question_text"] = new_text
                                
                                new_marks = question_content.get("marks")
                                if new_marks is not None and existing_q.get("marks") is None:
                                    existing_q["marks"] = new_marks
                            else:
                                existing_q.update(question_content)
                        else:
                            for subpart_key, subpart_content in question_content.items():
                                if subpart_key not in ["null", "", None]:
                                    if subpart_key not in existing_q:
                                        existing_q[subpart_key] = {}
                                    if isinstance(subpart_content, dict):
                                        existing_q[subpart_key].update(subpart_content)
                    else:
                        if question_key not in merged[norm_section]:
                            merged[norm_section][question_key] = {}
                        
                        if "question_id" in question_content:
                            merged[norm_section][question_key].update(question_content)
                        else:
                            for subpart_key, subpart_content in question_content.items():
                                if subpart_key not in ["null", "", None]:
                                    if subpart_key not in merged[norm_section][question_key]:
                                        merged[norm_section][question_key][subpart_key] = {}
                                    if isinstance(subpart_content, dict):
                                        merged[norm_section][question_key][subpart_key].update(subpart_content)
    
    # Final cleanup: ensure Q1 is under SectionB if it exists at top level (sanity check)
    if "Q1" in merged and "SectionB" in merged:
        merged["SectionB"]["Q1"].update(merged.pop("Q1"))
    elif "Q1" in merged:
        merged["SectionB"] = {"Q1": merged.pop("Q1")}
    
    # Clean up empty entries
    for section in list(merged.keys()):
        for qkey in list(merged[section].keys()):
            if not merged[section][qkey]:
                del merged[section][qkey]
        if not merged[section]:
            del merged[section]
    
    return merged


def remove_null_wrappers(schema: dict) -> dict:
    """
    Recursively remove 'null' wrapper keys from schema structure.
    GPT-4 sometimes wraps question data in {"null": {...}} which breaks grading.
    """
    if not isinstance(schema, dict):
        return schema
    
    cleaned = {}
    for key, value in schema.items():
        # If this is a "null" wrapper with a dict inside, unwrap it
        if key == "null" and isinstance(value, dict):
            # Merge the unwrapped content into parent level
            return remove_null_wrappers(value)
        
        # Otherwise recurse
        if isinstance(value, dict):
            # Check if this dict contains ONLY a "null" key
            if len(value) == 1 and "null" in value:
                # Unwrap it
                cleaned[key] = remove_null_wrappers(value["null"])
            else:
                cleaned[key] = remove_null_wrappers(value)
        else:
            cleaned[key] = value
    
    return cleaned


def build_solution_schema(solution_text: str) -> dict:
    """
    Build question schema from solution text.
    Uses Claude Sonnet 4 for all documents.
    Chunked processing is used for large documents to stay within context limits.
    """
    
    # Check if chunking is needed
    if len(solution_text) > MAX_CHUNK_CHARS:
        print(f"[Schema Builder] Large document ({len(solution_text)} chars). Using chunked processing.", flush=True)
        
        chunks = split_into_chunks(solution_text)
        print(f"[Schema Builder] Split into {len(chunks)} chunks", flush=True)
        
        schemas = []
        for i, chunk in enumerate(chunks):
            print(f"[Schema Builder] Processing chunk {i+1}/{len(chunks)} ({len(chunk)} chars)...", flush=True)
            
            schema = extract_schema_from_chunk(chunk, i + 1, len(chunks))
            if schema:
                schemas.append(schema)
            
            # Rate limit protection - wait between chunks
            if i < len(chunks) - 1:
                time.sleep(2)  # 2 second delay between chunks
        
        merged_schema = merge_schemas(schemas)
        print(f"[Schema Builder] Merged {len(schemas)} chunk schemas", flush=True)
        
        # Clean up null wrappers
        cleaned_schema = remove_null_wrappers(merged_schema)
        return cleaned_schema
    
    else:
        # Small document - process in single call using same logic as chunk
        print(f"[Schema Builder] Processing document in single call ({len(solution_text)} chars)...", flush=True)
        return extract_schema_from_chunk(solution_text, 1, 1)

