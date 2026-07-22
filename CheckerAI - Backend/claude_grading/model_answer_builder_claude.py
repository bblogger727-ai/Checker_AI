"""
Model Answer Builder — Claude Sonnet 4 Version

Uses Claude for the semantic chunk text extraction (Strategy 3).
Vision strategies (MCQ, garbled tables) still use OpenAI as they need image input.
"""

import os
import sys
import json
import re
import time
import copy
import fitz
from dotenv import load_dotenv

load_dotenv()

# Setup path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import anthropic

# Claude client
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
CLAUDE_MODEL = "claude-sonnet-4-6"

from app.services.model_answer_builder import (
    extract_pdf_text_tesseract,
    extract_mcq_answers_via_vision,
    _inject_mcq_answers,
    extract_table_answer_via_vision,
    split_into_semantic_chunks,
    merge_answer_results as merge_answer_results_legacy,
    _split_by_pages,
)

from claude_grading.pipeline_utils import normalize_schema_structure


def extract_solution_text_robust(pdf_path: str) -> str:
    """
    Extract text from Solution PDF using a robust approach:
    1. Try direct text extraction (fitz) - 100% accurate for digital PDFs.
    2. If text is too sparse (scanned), use Tesseract OCR.
    """
    print(f"[Claude ModelAnswerBuilder] Attempting robust text extraction from: {pdf_path}", flush=True)
    
    doc = fitz.open(pdf_path)
    direct_text = []
    total_chars = 0
    for i, page in enumerate(doc):
        text = page.get_text()
        total_chars += len(text.strip())
        direct_text.append(f"========== PAGE {i+1} ==========\n{text}\n")
    
    # Heuristic: if average chars per page < 100, it's likely a scan
    avg_chars = total_chars / len(doc) if len(doc) > 0 else 0
    
    if avg_chars > 100:
        print(f"[Claude ModelAnswerBuilder] ✓ Direct text extraction successful (Avg {avg_chars:.1f} chars/pg).", flush=True)
        doc.close()
        return "\n".join(direct_text)
    
    print(f"[Claude ModelAnswerBuilder] ! Direct text too sparse (Avg {avg_chars:.1f} chars/pg). Falling back to Tesseract OCR...", flush=True)
    doc.close()
    return extract_pdf_text_tesseract(pdf_path)


def _extract_json_from_claude(text: str) -> dict:
    """Extract JSON from Claude's response (may contain prose)."""
    text = text.strip()
    
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    if "```" in text:
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass
    
    brace_start = text.find('{')
    if brace_start >= 0:
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[brace_start:i+1])
                    except json.JSONDecodeError:
                        break
    
    raise json.JSONDecodeError("No valid JSON found in Claude response", text[:200], 0)


def _reconstruct_recursive_schema(flat_answers: dict, original_schema: dict) -> dict:
    """Helper to convert flat dict {'A-MCQ-1': 'ans'} back to nested schema structure."""
    result = copy.deepcopy(original_schema)
    
    def _inject_answers(node):
        if not isinstance(node, dict):
            return
        qid = node.get("question_id")
        qnum = node.get("question_number") or ""
        subpart = node.get("subpart") or ""
        
        if qid:
            # 1. Exact match (highest priority)
            if qid in flat_answers:
                node["model_answer"] = flat_answers[qid]
                print(f"[Claude Aligner] Exact match for {qid}")
            # 2. Strict matching for subparts/numbers
            else:
                for k, v in flat_answers.items():
                    # k might be "Q1" or "Q2a" or "2a"
                    k_clean = str(k).strip()
                    
                    match = False
                    # Case 1: k is the question number (e.g. "Q1" or "1")
                    if (k_clean == qnum or f"Q{k_clean}" == qnum or f"MCQ-{k_clean}" == qid) and not subpart:
                        match = True
                    # Case 2: k is qnum + subpart (e.g. "2a" or "Q2a")
                    elif subpart and (k_clean == f"{qnum}{subpart}" or k_clean == f"Q{qnum}{subpart}"):
                        match = True
                    # Case 3: k matches the last part of the ID
                    elif k_clean == qid.split('-')[-1]:
                        # Only allow if it's not a generic subpart like 'a', 'b'
                        if k_clean not in ['a', 'b', 'c', 'd', 'i', 'ii', 'iii']:
                            match = True
                    # Case 4: k matches numeric part of question number (e.g. k="3" matches qnum="Q3")
                    elif re.search(r'\d+', k_clean) and re.search(r'\d+', qnum) and re.search(r'\d+', k_clean).group(0) == re.search(r'\d+', qnum).group(0):
                        match = True

                    if match:
                        print(f"[Claude Aligner] Mapped '{k}' to {qid}")
                        node["model_answer"] = v
                        break
                        
        for k, v in node.items():
            if isinstance(v, dict):
                _inject_answers(v)
                
    _inject_answers(result)
    return result


def extract_answers_from_chunk_claude(chunk_text: str, question_schema: dict, chunk_label: str, chunk_num: int, total_chunks: int) -> dict:
    """
    Extract model answers from a single semantic chunk using Claude Sonnet 4.
    Returns a partial schema dict with model_answer fields populated.
    """
    # Extract IDs mapping to Question Texts so Claude knows what to look for
    id_map = {}
    def _extract_ids(node):
        if not isinstance(node, dict): return
        qid = node.get("question_id")
        qtext = node.get("question") or node.get("question_text")
        if qid and qtext:
            id_map[qid] = qtext[:200] + "..." if len(qtext) > 200 else qtext
        for k, v in node.items():
            if isinstance(v, dict):
                _extract_ids(v)
    _extract_ids(question_schema)
    
    prompt = f"""You are an expert CA examiner.
You are given chunk {chunk_num}/{total_chunks} of the solution text (label: '{chunk_label}').

Your task is to extract EVERYTHING that looks like an answer to these Question IDs.

**TARGET QUESTIONS & TEXT (FOR CONTEXT):**
{json.dumps(id_map, indent=2)}

**NON-NEGOTIABLE RULES:**
1. **EXTRACT EVERYTHING**: If you see "Answer to Question X" or "Question X" or just a block of text that clearly corresponds to the question text provided above, EXTRACT IT.
2. The extracted text MUST contain the **entirety** of the solution text. Include tables, calculations, and working notes.
3. **DO NOT SUMMARIZE**. Do not truncate.
4. **FORMATTING**: Preserve markdown tables and calculations exactly.
5. If an answer is NOT found in this chunk, DO NOT include its ID in the output.

---
Chunk Text:
{chunk_text}

IMPORTANT: Respond with ONLY a flat JSON object mapping the `Question ID` to the exact extracted text string. 
Example format:
{{
  "PART I-Q1": "Full text...",
  "PART I-Q5": "Full text..."
}}
No explanation, no prose — just the raw JSON."""

    for attempt in range(2):
        try:
            print(f"[Claude ModelAnswerBuilder]   Attempt {attempt+1} for chunk '{chunk_label}'...", flush=True)
            
            # On second attempt, mention "DO NOT return empty JSON if you find anything"
            current_prompt = prompt
            if attempt > 0:
                current_prompt += "\n\nCRITICAL: If you find ANY information relevant to the target questions, you MUST return it. DO NOT return an empty object if there is relevant data."

            response = claude_client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=8192,
                system="You are a strict JSON extraction assistant. Output ONLY a flat JSON mapping of question IDs to extracted text. Do not output anything else. If no answers are found, return {}.",
                messages=[
                    {"role": "user", "content": current_prompt}
                ],
                temperature=0 if attempt == 0 else 0.2
            )
    
            content = response.content[0].text.strip()
            
            if not content:
                print(f"[Claude ModelAnswerBuilder]   Warning: Received empty content from Claude on attempt {attempt+1}.", flush=True)
                continue

            flat_results = _extract_json_from_claude(content)
            
            print(f"[Claude ModelAnswerBuilder] Chunk '{chunk_label}' → Claude extracted {len(flat_results)} answer(s). Keys: {list(flat_results.keys())}", flush=True)
    
            # Reconstruct into nested schema for the pipeline
            return _reconstruct_recursive_schema(flat_results, question_schema)
    
        except Exception as e:
            print(f"[Claude ModelAnswerBuilder]   Attempt {attempt+1} failed: {e}", flush=True)
            if attempt == 0:
                time.sleep(2) # Wait before retry
            else:
                # Final failure for this chunk
                print(f"[Claude ModelAnswerBuilder]   Final failure for chunk '{chunk_label}'. Proceeding with empty results.", flush=True)
                return {}
    
    return {}


def _schema_has_mcqs(schema: dict) -> bool:
    """Recursively check if any section contains MCQ questions."""
    for section in schema.values():
        if isinstance(section, dict):
            if "MCQ" in section:
                return True
            # Recurse for deeper nesting if needed
            for val in section.values():
                if isinstance(val, dict) and "MCQ" in val:
                    return True
    return False


def build_model_answers_claude(question_schema: dict, solution_text: str = None, pdf_path: str = None) -> dict:
    """
    Build complete model answers schema from questions and solution text.
    Uses Claude for text extraction, OpenAI vision for MCQ/garbled tables.
    
    If solution_text is NOT provided, it will be extracted robustly from pdf_path.
    """
    final_schema = copy.deepcopy(question_schema)

    # 0. Robust Text Extraction if needed
    if not solution_text and pdf_path:
        solution_text = extract_solution_text_robust(pdf_path)
    
    if not solution_text:
        print("[Claude ModelAnswerBuilder] Error: No solution text provided or extracted.", flush=True)
        return final_schema

    # ── Strategy 1: MCQ vision extraction (still OpenAI) ──────────────
    if pdf_path:
        if _schema_has_mcqs(final_schema):
            print("[Claude ModelAnswerBuilder] Strategy 1: Extracting MCQ answers via vision (OpenAI)...", flush=True)
            mcq_answers = extract_mcq_answers_via_vision(pdf_path, solution_text, final_schema)
            if mcq_answers:
                _inject_mcq_answers(final_schema, mcq_answers)
                print(f"[Claude ModelAnswerBuilder] Injected {len(mcq_answers)} MCQ model answers.", flush=True)
        else:
            print("[Claude ModelAnswerBuilder] Strategy 1: Skipping MCQ vision extraction — no MCQs found in schema.", flush=True)

    # ── Strategy 2: Vision for Q1 garbled table (still OpenAI) ────────
    if pdf_path:
        # Check if B-Q1 or Q1 exists in SectionB
        has_q1 = "Q1" in final_schema.get("SectionB", {}) or "Q1" in final_schema.get("PART_I", {})
        if has_q1 and ("SectionB" in final_schema or "PART_I" in final_schema):
            # Only run if explicitly needed (marker found or known problematic paper)
            if "ANSWER 1" in solution_text or "QUESTION 1" in solution_text:
                q1_answer = extract_table_answer_via_vision(pdf_path, solution_text, "B-Q1", "ANSWER 1")
                if q1_answer:
                    section = "SectionB" if "SectionB" in final_schema else "PART_I"
                    final_schema[section]["Q1"]["model_answer"] = q1_answer
                    print(f"[Claude ModelAnswerBuilder] Injected vision-extracted Q1 model answer into {section}.", flush=True)

    # ── Strategy 2.5: Vision for Q3 (specifically for 15166) ────────
    if pdf_path and "Question: 3" in solution_text and "ABC Ltd. prepares consolidated financial statements" in solution_text:
        print("[Claude ModelAnswerBuilder] Detected Paper 15166 Q3. Extracting via Vision because of Tesseract garbling...", flush=True)
        try:
            from app.services.model_answer_builder import _render_page_as_base64
            from app.core.openai_client import client
            # In 15166 SA, Q3 answer spans pages 4 and 5
            encoded_pages = []
            for p in [4, 5]:
                b64 = _render_page_as_base64(pdf_path, p)
                if b64:
                    encoded_pages.append(b64)
            
            if encoded_pages:
                prompt_vision = """You are an expert CA examiner.
CRITICAL CONTEXT: These images are from a purely FICTIONAL, publicly available MOCK EXAM PAPER for educational purposes. They do NOT contain real company data, personal identifiable information (PII), or sensitive financial records.

Your task is to extract the ENTIRE MODEL ANSWER for Question 3 (Computation of goodwill impairment and NCI) from these mock exam images.
Include ALL working notes. Preserve the tables, markdown, and numerical calculations EXACTLY as written in the images.
Do NOT summarize. Return ONLY the extracted text, no explanation."""
                
                content_list = [{"type": "text", "text": prompt_vision}]
                for b64 in encoded_pages:
                    content_list.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
                
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": content_list}],
                    temperature=0
                )
                q3_ans = response.choices[0].message.content.strip()
                if "Q3" in final_schema.get("SectionA", {}):
                    final_schema["SectionA"]["Q3"]["model_answer"] = q3_ans
                    print(f"[Claude ModelAnswerBuilder] Injected vision-extracted 15166 Q3 model answer ({len(q3_ans)} chars).", flush=True)
        except Exception as e:
            print(f"[Claude ModelAnswerBuilder] 15166 Q3 Vision Error: {e}", flush=True)

    # ── Strategy 3: Semantic text chunking using CLAUDE ────────────────
    print("[Claude ModelAnswerBuilder] Strategy 3: Semantic chunked text extraction (Claude)...", flush=True)
    semantic_chunks = split_into_semantic_chunks(solution_text)
    # If no ANSWER markers were found, split_into_semantic_chunks used 4 pages.
    # Let's override it here if it looks like it used the fallback.
    if len(semantic_chunks) > 0 and "pages_" in semantic_chunks[0][0]:
        print("[Claude ModelAnswerBuilder] Overriding fallback chunk size to 3 pages...", flush=True)
        semantic_chunks = _split_by_pages(solution_text, pages_per_chunk=3)

    answer_chunks = [(label, text) for label, text in semantic_chunks if label != "MCQ_QUESTIONS"]

    print(f"[Claude ModelAnswerBuilder] Processing {len(answer_chunks)} semantic answer chunks with Claude...", flush=True)

    partial_results = []
    for i, (label, chunk_text) in enumerate(answer_chunks):
        if not chunk_text.strip():
            continue

        # Skip Q1 if vision already got it
        has_q1_ans = False
        def _check_q1(node):
            nonlocal has_q1_ans
            if isinstance(node, dict):
                if node.get("question_id") in ["B-Q1", "PART_I-Q1"] and node.get("model_answer"):
                    has_q1_ans = True
                for v in node.values(): _check_q1(v)
        _check_q1(final_schema)

        if "ANSWER 1" in label.upper() and pdf_path and has_q1_ans:
            print(f"[Claude ModelAnswerBuilder] Skipping '{label}' — already extracted via vision.", flush=True)
            continue

        print(f"[Claude ModelAnswerBuilder] Processing chunk {i+1}/{len(answer_chunks)}: '{label}' ({len(chunk_text)} chars)...", flush=True)
        partial = extract_answers_from_chunk_claude(chunk_text, question_schema, label, i + 1, len(answer_chunks))
        if partial:
            partial_results.append(partial)

        if i < len(answer_chunks) - 1:
            time.sleep(1)

    final_schema = merge_answer_results(final_schema, partial_results)
    print(f"[Claude ModelAnswerBuilder] Merged {len(partial_results)} text chunks into schema.", flush=True)

    # ── Final Robustness: Normalize structure ──────────────────────────
    print("[Claude ModelAnswerBuilder] Normalizing schema structure...", flush=True)
    final_schema = normalize_schema_structure(final_schema)

    return final_schema


def merge_answer_results(original_schema: dict, partial_results: list) -> dict:
    """
    Merge partial results into the final schema.
    Populates 'model_answer' in the original schema from partial results.
    Target-agnostic: finds question IDs anywhere in the schema tree.
    """
    final_schema = copy.deepcopy(original_schema)
    
    # Flatten partial results into a single map of qid -> list of chunks
    extracted_map = {}
    for partial in partial_results:
        def _flatten(node):
            if not isinstance(node, dict): return
            qid = node.get("question_id")
            ans = node.get("model_answer")
            if qid and ans:
                if qid not in extracted_map: extracted_map[qid] = []
                extracted_map[qid].append(ans)
            for v in node.values():
                if isinstance(v, dict): _flatten(v)
        _flatten(partial)

    # Inject into final_schema
    def _inject(node):
        if not isinstance(node, dict): return
        qid = node.get("question_id")
        if qid in extracted_map:
            # Combine chunks, preventing exact duplicates
            combined = []
            for chunk in extracted_map[qid]:
                if chunk and chunk.strip() and chunk not in combined:
                    combined.append(chunk)
            if combined:
                node["model_answer"] = "\n\n".join(combined)
                print(f"[Claude ModelAnswerBuilder] Integrated model answer for {qid}")
        
        for v in node.values():
            if isinstance(v, dict): _inject(v)
            
    _inject(final_schema)
    return final_schema
