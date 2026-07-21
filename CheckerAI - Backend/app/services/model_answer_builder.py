"""
Model Answer Builder Service — v2

Three-strategy extraction pipeline:
  1. VISION: MCQ answer table page → gpt-4o vision (Tesseract garbles structured tables)
  2. VISION: Garbled table pages (e.g. Q1 ITC tables) → gpt-4o vision
  3. TEXT:   Semantic chunks split by ANSWER blocks → gpt-4o text (for all descriptive answers)

This avoids the two root-cause bugs from v1:
  Bug A: Tesseract cannot parse MCQ answer tables → garbled text → wrong/random MCQ answers
  Bug B: 40k-char monolith chunk overloads GPT-4o → Q2/Q3 answers dropped randomly
"""

from app.core.openai_client import client
import json
import re
import time
import fitz
import subprocess
import tempfile
import os
import base64


# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────

# Tesseract garbled-content heuristic: if a "table-ish" page has fewer
# than this many real alpha words per line on average, treat it as garbled.
GARBLE_WORD_RATIO_THRESHOLD = 1.8

# Maximum chars for a single semantic chunk sent to GPT-4o text API
MAX_SEMANTIC_CHUNK_CHARS = 20000


# ─────────────────────────────────────────────────────────────
# Tesseract extraction (unchanged, used in Stage 2)
# ─────────────────────────────────────────────────────────────

def extract_pdf_text_tesseract(pdf_path: str) -> str:
    """
    Extract text from PDF using Tesseract OCR page by page.
    Returns full text with === PAGE N === markers.
    """
    print(f"[ModelAnswerBuilder] Extracting text with Tesseract from {pdf_path}...", flush=True)
    doc = fitz.open(pdf_path)
    all_text = []

    with tempfile.TemporaryDirectory() as tmpdir:
        for i, page in enumerate(doc):
            page_num = i + 1
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat)
            img_path = os.path.join(tmpdir, f"page_{page_num}.png")
            pix.save(img_path)

            try:
                result = subprocess.run(
                    ["tesseract", img_path, "stdout", "-l", "eng", "--psm", "6"],
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                text = result.stdout
                all_text.append(f"========== PAGE {page_num} ==========\n{text}\n")
            except Exception as e:
                print(f"Warning: Tesseract failed on page {page_num}: {e}")

    doc.close()
    return "\n".join(all_text)


# ─────────────────────────────────────────────────────────────
# Strategy 1: MCQ Vision Extraction
# ─────────────────────────────────────────────────────────────

def _find_mcq_answer_page(sa_text: str) -> int | None:
    """
    Detect which SA page contains the MCQ answer table.
    Tesseract reads the bold heading 'MCQ ANSWER' correctly even when the table cells are garbled.
    Returns 1-indexed page number, or None if not found.
    """
    # Check each page block for the keyword
    page_blocks = re.split(r'========== PAGE (\d+) ==========', sa_text)
    # page_blocks: ['', '1', '<page1_text>', '2', '<page2_text>', ...]
    for i in range(1, len(page_blocks) - 1, 2):
        page_num = int(page_blocks[i])
        page_text = page_blocks[i + 1]
        
        # Enhanced keyword list
        keywords = [
            "MCQ ANSWER", "MCQ No.", "Most Appropriate Answer", 
            "Multiple Choice Questions", "Answer Key", "Division A"
        ]
        
        found = False
        p_text_upper = page_text.upper()
        for kw in keywords:
            if kw.upper() in p_text_upper:
                # Secondary check: MCQ pages are usually mostly empty or tabular
                # and usually occur in the first few pages or last few pages of the SA.
                found = True
                break
        
        if found:
            print(f"[ModelAnswerBuilder] Found MCQ answer table candidate on page {page_num}", flush=True)
            return page_num
            
    return None


def _render_page_as_base64(pdf_path: str, page_num: int) -> str:
    """
    Render a specific PDF page (1-indexed) as a PNG and return base64 string.
    """
    import fitz
    import base64
    doc = fitz.open(pdf_path)
    page = doc[page_num - 1]
    mat = fitz.Matrix(2.5, 2.5)  # Higher DPI for vision clarity
    pix = page.get_pixmap(matrix=mat)
    png_bytes = pix.tobytes("png")
    doc.close()
    return base64.b64encode(png_bytes).decode("utf-8")


def _find_mcq_answer_page(pdf_path: str) -> int:
    """Find the page number containing the MCQ answer table using Tesseract text."""
    doc = fitz.open(pdf_path)
    for i in range(len(doc)):
        # Skip the first page often if it is a cover page (heuristic)
        if i == 0 and len(doc) > 5:
            continue
            
        page = doc[i]
        text = page.get_text().lower()
        
        # Look for table headers or indicators
        if "division a" in text and "mcq" in text and "answer" in text:
            doc.close()
            return i + 1
        if "multiple choice questions" in text and "answer" in text and ("table" in text or "no." in text):
            doc.close()
            return i + 1
            
    doc.close()
    return None


def _find_mcq_page_via_vision(pdf_path: str) -> int | None:
    """Fallback: gpt-4o search for MCQ answer table page by probing."""
    doc = fitz.open(pdf_path)
    total = len(doc)
    # Search first 15 pages (usually near front) and last 5 pages
    candidates = list(range(1, min(16, total + 1)))
    if total > 20:
        candidates += list(range(total - 4, total + 1))
    
    candidates = list(dict.fromkeys(candidates)) # Deduplicate
    candidates.sort()

    for pg_num in candidates:
        # Skip cover page if it's the first
        if pg_num == 1 and total > 5:
            continue
            
        print(f"[ModelAnswerBuilder] Vision-probing page {pg_num} for MCQ table...", flush=True)
        img_b64 = _render_page_as_base64(pdf_path, pg_num)
        
        prompt = "Does this page contain a Multiple Choice Question (MCQ) ANSWER TABLE (a table with numbers and letters like 1-a, 2-c)? Return ONLY 'YES' or 'NO'."
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}", "detail": "low"}}
                ]}],
                max_tokens=10,
                temperature=0
            )
            res = response.choices[0].message.content.strip().upper()
            if "YES" in res:
                print(f"[ModelAnswerBuilder] Vision confirmed MCQ table on page {pg_num}", flush=True)
                doc.close()
                return pg_num
        except Exception as e:
            print(f"  Probe error on page {pg_num}: {e}")
            
    doc.close()
    return None


def extract_mcq_answers_via_vision(pdf_path: str, sa_text: str, schema: dict) -> dict:
    """
    Strategy 1: Use gpt-4o vision to read the MCQ answer table page.
    Returns a dict mapping question_id → model_answer string.
    """
    mcq_page = _find_mcq_answer_page(pdf_path)
    
    if mcq_page is None:
        print("[ModelAnswerBuilder] MCQ answer table page not found in Tesseract text. Trying vision-based search...", flush=True)
        mcq_page = _find_mcq_page_via_vision(pdf_path)
        
    if mcq_page is None:
        print("[ModelAnswerBuilder] No MCQ page found even with vision search. Skipping.", flush=True)
        return {}

    print(f"[ModelAnswerBuilder] Strategy 1: Vision extraction on MCQ answer table (page {mcq_page})...", flush=True)

    # Build MCQ reference list from schema so GPT knows option texts
    mcq_ref = {}
    try:
        for num_str, q_data in schema.get("SectionA", {}).get("MCQ", {}).items():
            mcq_ref[num_str] = q_data.get("question", "")
    except Exception:
        pass

    # Also fetch the surrounding pages (MCQ questions are on earlier pages)
    # We provide the answer table page only — GPT-4o can match number to option letter
    image_b64 = _render_page_as_base64(pdf_path, mcq_page)

    prompt = """This image shows an MCQ Answer Table from a CA exam answer sheet.
The table has two columns: MCQ number (1, 2, 3...) and the correct option letter (a/b/c/d).

Extract every MCQ number and its correct answer option letter.

Return ONLY a JSON object like this:
{
  "1": "c",
  "2": "b",
  "3": "b",
  ...
}

Rules:
- Include ALL MCQ numbers visible in the table.
- Answer must be lowercase single letter (a, b, c, or d).
- If a number has no clear answer, omit it.
- Return ONLY the JSON, no explanation.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}", "detail": "high"}}
                    ]
                }
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=500
        )
        raw = response.choices[0].message.content.strip()
        letter_map = json.loads(raw)  # {"1": "c", "2": "b", ...}

        print(f"[ModelAnswerBuilder] Vision MCQ extraction: got {len(letter_map)} answers", flush=True)

        # Now build full model_answer strings by looking up option text from the schema
        result = {}
        mcq_schema = schema.get("SectionA", {}).get("MCQ", {})
        
        # Build a helper map from numeric suffix to actual question data
        num_to_q = {}
        for qid, q_data in mcq_schema.items():
            # Extract number from ID like 'A-MCQ-4' or 'MCQ-4' or '4'
            match = re.search(r'(\d+)$', str(q_data.get("question_id", "")))
            if match:
                num_to_q[match.group(1)] = q_data
            elif re.search(r'(\d+)$', str(qid)):
                num_to_q[re.search(r'(\d+)$', str(qid)).group(1)] = q_data

        for num_str, letter in letter_map.items():
            q_data = num_to_q.get(num_str)
            if not q_data:
                # Fallback to direct numeric key if available
                q_data = mcq_schema.get(num_str)
            
            qid = q_data.get("question_id") if q_data else f"A-MCQ-{num_str}"
            q_text = q_data.get("question_text", q_data.get("question", "")) if q_data else ""
            
            option_text = _find_option_text_in_schema(q_text, letter) if q_text else ""
            if option_text:
                result[qid] = f"({letter}) {option_text}"
            else:
                result[qid] = f"({letter})"
            print(f"  MCQ {num_str} (mapped to {qid}) → {result[qid]}", flush=True)

        return result

    except Exception as e:
        print(f"[ModelAnswerBuilder] Strategy 1 (MCQ vision) error: {e}", flush=True)
        return {}


def _find_option_text_in_schema(question_text: str, letter: str) -> str:
    """
    Extract the text of a specific option letter from a question's text field.
    The schema question field contains lines like:
      '(a) Oklahoma...', '(b) Rajasthan...', etc.
    We search within question_text only — never in the full SA body.
    """
    letter_upper = letter.upper()
    letter_lower = letter.lower()

    # Patterns: (a), (A), a., A.
    patterns = [
        rf'\({letter_upper}\)\s*([^\n\(\)]+)',
        rf'\({letter_lower}\)\s*([^\n\(\)]+)',
        rf'(?:^|\s){letter_upper}\.\s+([^\n]+)',
    ]
    for pat in patterns:
        matches = re.findall(pat, question_text, re.MULTILINE)
        for m in matches:
            m = m.strip().rstrip('.,;—–')
            # Discard very short matches or clearly wrong ones
            if 3 < len(m) < 250:
                return m
    return ""


# ─────────────────────────────────────────────────────────────
# Strategy 2: Garbled Table Vision Extraction (e.g. Q1)
# ─────────────────────────────────────────────────────────────

def _is_page_garbled(page_text: str) -> bool:
    """
    Heuristic: detect if Tesseract produced garbled output for a table page.
    A garbled page has many short "lines" with very few real words.
    """
    lines = [l.strip() for l in page_text.split('\n') if l.strip()]
    if len(lines) < 3:
        return False

    # Count lines that look like garble: very few real words (alpha 3+ chars)
    garble_lines = 0
    for line in lines:
        words = re.findall(r'[a-zA-Z]{3,}', line)
        if len(words) < 2 and len(line) > 5:
            garble_lines += 1

    ratio = garble_lines / len(lines)
    return ratio > 0.5


def _detect_answer_table_pages(sa_text: str, answer_label: str) -> list:
    """
    Find pages associated with a specific ANSWER label (e.g. "ANSWER 1").
    Returns list of 1-indexed page numbers that are garbled.
    """
    page_blocks = re.split(r'========== PAGE (\d+) ==========', sa_text)
    garbled_pages = []

    answer_started = False
    for i in range(1, len(page_blocks) - 1, 2):
        page_num = int(page_blocks[i])
        page_text = page_blocks[i + 1]

        if answer_label.upper() in page_text.upper():
            answer_started = True

        if answer_started:
            if _is_page_garbled(page_text):
                garbled_pages.append(page_num)
            # Stop after 3 consecutive pages after the answer starts
            if len(garbled_pages) >= 3:
                break

    return garbled_pages


def extract_table_answer_via_vision(pdf_path: str, sa_text: str, question_id: str, answer_label: str) -> str:
    """
    Strategy 2: Use gpt-4o vision for questions whose SA pages are garbled tables.
    Returns the extracted model answer text, or "" if failed.
    """
    garbled_pages = _detect_answer_table_pages(sa_text, answer_label)

    if not garbled_pages:
        print(f"[ModelAnswerBuilder] No garbled pages found for {answer_label}. Skipping vision.", flush=True)
        return ""

    print(f"[ModelAnswerBuilder] Strategy 2: Vision extraction for {question_id} on pages {garbled_pages}...", flush=True)

    # Render all garbled pages and combine
    image_contents = []
    for page_num in garbled_pages:
        image_b64 = _render_page_as_base64(pdf_path, page_num)
        image_contents.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{image_b64}", "detail": "high"}
        })

    prompt = f"""These images show pages from a CA exam solution answer sheet.
They contain the answer to question {answer_label}.

Extract the COMPLETE answer text including:
- All computation tables (preserving rows and columns in markdown table format)
- All numerical values, labels, and column headers
- All notes and explanations following the table
- All section headings

Return ONLY the answer text. No JSON wrapper. No introduction. Start directly from where the answer begins.
Preserve the structure as closely as possible. Use markdown table format for any tabular data.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}] + image_contents
                }
            ],
            temperature=0,
            max_tokens=3000
        )
        answer_text = response.choices[0].message.content.strip()
        print(f"[ModelAnswerBuilder] Vision table extraction for {question_id}: {len(answer_text)} chars", flush=True)
        return answer_text

    except Exception as e:
        print(f"[ModelAnswerBuilder] Strategy 2 (table vision) error for {question_id}: {e}", flush=True)
        return ""


# ─────────────────────────────────────────────────────────────
# Strategy 3: Semantic Chunking
# ─────────────────────────────────────────────────────────────

def split_into_semantic_chunks(solution_text: str) -> list:
    """
    Split the SA text into meaningful chunks based on ANSWER block markers.

    The SA text contains markers like:
      'ANSWER 1:-', 'ANSWER 2 (A)', 'ANSWER 3 (B):-', etc.

    We split on these so each chunk contains ONE (or a few related) answer block(s),
    preventing the overloaded-chunk problem where GPT-4o drops answers from large chunks.
    """
    # Pattern that matches ANSWER headers robustly
    # Supports: "ANSWER 1", "Answer: 1", "Ans 1", "Question: 1", "Q.1", etc.
    answer_pattern = re.compile(
        r'(?:^|\n)((?:ANSWER|Answer|Ans|Question|Q)\s*[:.-]?\s*\d+[\s\(]?[^:\n]{0,20}(?::-|:|-|))',
        re.MULTILINE | re.IGNORECASE
    )

    splits = list(answer_pattern.finditer(solution_text))

    if len(splits) < 2:
        # Fallback: split by page into groups of 4 pages max
        print("[ModelAnswerBuilder] No ANSWER markers found. Falling back to page-based chunking.", flush=True)
        return _split_by_pages(solution_text, pages_per_chunk=4)

    chunks = []

    # Content before the first ANSWER = MCQ questions section (skip for text extraction,
    # MCQs are handled by vision strategy 1)
    pre_answer = solution_text[:splits[0].start()].strip()
    if pre_answer:
        chunks.append(("MCQ_QUESTIONS", pre_answer))

    # Each ANSWER block
    for i, match in enumerate(splits):
        label = match.group(1).strip().rstrip(':-').strip()  # e.g. "ANSWER 1" or "ANSWER 2 (A)"
        start = match.start()
        end = splits[i + 1].start() if i + 1 < len(splits) else len(solution_text)
        chunk_text = solution_text[start:end].strip()

        # Group small consecutive chunks if under limit (to reduce API calls)
        if chunks and chunks[-1][0] != "MCQ_QUESTIONS":
            prev_label, prev_text = chunks[-1]
            if len(prev_text) + len(chunk_text) < MAX_SEMANTIC_CHUNK_CHARS:
                chunks[-1] = (prev_label + " + " + label, prev_text + "\n\n" + chunk_text)
                continue

        chunks.append((label, chunk_text))

    print(f"[ModelAnswerBuilder] Semantic split: {len(chunks)} chunks", flush=True)
    for label, text in chunks:
        print(f"  → '{label}': {len(text)} chars", flush=True)

    return chunks


def _split_by_pages(solution_text: str, pages_per_chunk: int = 4) -> list:
    """Fallback: group N pages per chunk."""
    page_pattern = r'(========== PAGE \d+ ==========)'
    parts = re.split(page_pattern, solution_text)
    pages = []
    for i in range(1, len(parts) - 1, 2):
        pages.append(parts[i] + "\n" + parts[i + 1])

    chunks = []
    for i in range(0, len(pages), pages_per_chunk):
        group = pages[i:i + pages_per_chunk]
        chunks.append((f"pages_{i+1}_to_{i+len(group)}", "\n\n".join(group)))
    return chunks


# ─────────────────────────────────────────────────────────────
# Text Extraction from Semantic Chunks
# ─────────────────────────────────────────────────────────────

def extract_answers_from_chunk(chunk_text: str, question_schema: dict, chunk_label: str, chunk_num: int, total_chunks: int) -> dict:
    """
    Extract model answers from a single semantic chunk using GPT-4o text.
    Returns a partial schema dict with model_answer fields populated.
    """
    prompt = f"""You are an expert CA examiner.
You are given chunk {chunk_num}/{total_chunks} of the solution text (label: '{chunk_label}').

Your task:
1. Review the provided Question Schema.
2. Search THIS CHUNK of text for answers to ANY of those questions.
3. If an answer is found, extract it into the `model_answer` field.

**NON-NEGOTIABLE RULES:**
1. **EXTRACT EVERYTHING**: The `model_answer` MUST contain the **entirety** of the solution text for that question.
   - Include ALL introductory lines.
   - Include ALL tables, calculations, and working notes.
   - Include ALL reasoning and legal provisions.
   - **DO NOT SUMMARIZE**. Do not truncate.
   - Every word in the solution text (except the question itself) MUST be assigned to a model answer.

2. **MCQ HANDLING**: 
   - Look for a specialized table/box at the **END OF THE SECTION** (e.g. "MCQ No. Most Appropriate Answer").
   - Construct the answer by combining the Option + Text.
   - **CRITICAL**: If the solution text provides reasoning for the MCQ (not just the table), INCLUDE THE REASONING.

3. **FORMATTING**:
   - Preserve markdown tables.
   - Preserve lists and bullet points.

4. **EMPTY ANSWERS**:
   - If an answer is NOT found in this chunk, leave `model_answer` as null (or "").
   - Do NOT hallucinate answers.

---
Question Schema (Look for these IDs):
{json.dumps(question_schema, indent=2)}

---
Chunk Text:
{chunk_text}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a strict JSON extraction assistant. Return the same schema structure with model_answer fields populated."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0
        )

        content = response.choices[0].message.content.strip()

        # Clean markdown fences if present
        if content.startswith("```"):
            content = re.sub(r'^```json?\n?', '', content)
            content = re.sub(r'\n?```$', '', content)

        return json.loads(content)

    except Exception as e:
        print(f"[ModelAnswerBuilder] Error processing chunk '{chunk_label}': {e}", flush=True)
        return {}


# ─────────────────────────────────────────────────────────────
# Merge partial results
# ─────────────────────────────────────────────────────────────

def merge_answer_results(original_schema: dict, partial_results: list) -> dict:
    """
    Merge partial results into the final schema.
    Populates 'model_answer' in the original schema from partial results.
    """
    final_schema = json.loads(json.dumps(original_schema))

    def update_recursive(target, source):
        for key, value in source.items():
            if isinstance(value, dict):
                if key not in target:
                    continue
                update_recursive(target[key], value)
            else:
                if key == "model_answer":
                    # PROTECTION: If this is an MCQ and we already have a vision answer, skip
                    if target.get("mcq_extracted_via_vision"):
                        continue

                    if value and isinstance(value, str) and len(value.strip()) > 0:
                        if "model_answer" in target and target["model_answer"]:
                            if value.strip() not in target["model_answer"]:
                                target["model_answer"] += "\n\n" + value
                        else:
                            target["model_answer"] = value
                elif key == "marks":
                    target[key] = value

    for partial in partial_results:
        update_recursive(final_schema, partial)

    return final_schema


def _inject_mcq_answers(schema: dict, mcq_answer_map: dict):
    """
    Inject vision-extracted MCQ answers directly into the schema.
    Uses flexible matching to handle ID inconsistencies (A-MCQ-1 vs MCQ-1 vs 1).
    """
    mcq_section = schema.get("SectionA", {}).get("MCQ", {})
    
    # 1. Try exact ID match
    for num_str, q_data in mcq_section.items():
        qid = q_data.get("question_id", f"A-MCQ-{num_str}")
        if qid in mcq_answer_map:
            q_data["model_answer"] = mcq_answer_map[qid]
            q_data["mcq_extracted_via_vision"] = True
            
    # 2. Try matching by numeric suffix if still empty
    for num_str, q_data in mcq_section.items():
        if q_data.get("mcq_extracted_via_vision"):
            continue
            
        qid = q_data.get("question_id", "")
        match_suffix = re.search(r'(\d+)$', str(qid))
        if match_suffix:
            target_num = match_suffix.group(1)
            # Find in map by searching its keys for that number
            for map_qid, ans in mcq_answer_map.items():
                map_match = re.search(r'(\d+)$', str(map_qid))
                if map_match and map_match.group(1) == target_num:
                    q_data["model_answer"] = ans
                    q_data["mcq_extracted_via_vision"] = True
                    break


# ─────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────

def build_model_answers(question_schema: dict, solution_text: str, pdf_path: str = None) -> dict:
    """
    Build complete model answers schema from questions and solution text.

    Three-strategy pipeline:
      1. Vision: MCQ answer table page
      2. Vision: Garbled table pages (Q1-type computation tables)
      3. Text:   Semantic chunks for all readable descriptive answers
    """
    import copy
    final_schema = copy.deepcopy(question_schema)

    # ── Strategy 1: MCQ vision extraction ──────────────────────────────
    if pdf_path:
        print("[ModelAnswerBuilder] Strategy 1: Extracting MCQ answers via vision...", flush=True)
        mcq_answers = extract_mcq_answers_via_vision(pdf_path, solution_text, final_schema)
        if mcq_answers:
            _inject_mcq_answers(final_schema, mcq_answers)
            print(f"[ModelAnswerBuilder] Injected {len(mcq_answers)} MCQ model answers.", flush=True)
    else:
        print("[ModelAnswerBuilder] No PDF path provided. Skipping vision strategies.", flush=True)

    # ── Strategy 2: Vision for Q1 garbled table ─────────────────────────
    if pdf_path:
        # Detect if Q1 answer page is garbled and needs vision
        q1_answer = extract_table_answer_via_vision(pdf_path, solution_text, "B-Q1", "ANSWER 1")
        if q1_answer:
            if "Q1" in final_schema.get("SectionB", {}):
                final_schema["SectionB"]["Q1"]["model_answer"] = q1_answer
                print("[ModelAnswerBuilder] Injected vision-extracted Q1 model answer.", flush=True)

    # ── Strategy 3: Semantic text chunking for descriptive answers ──────
    print("[ModelAnswerBuilder] Strategy 3: Semantic chunked text extraction...", flush=True)
    semantic_chunks = split_into_semantic_chunks(solution_text)

    # Skip MCQ_QUESTIONS chunk — already handled by vision
    answer_chunks = [(label, text) for label, text in semantic_chunks if label != "MCQ_QUESTIONS"]

    print(f"[ModelAnswerBuilder] Processing {len(answer_chunks)} semantic answer chunks...", flush=True)

    partial_results = []
    for i, (label, chunk_text) in enumerate(answer_chunks):
        # Skip empty chunks
        if not chunk_text.strip():
            continue

        # Skip Q1 chunk if vision already extracted it
        if "ANSWER 1" in label.upper() and pdf_path and final_schema.get("SectionB", {}).get("Q1", {}).get("model_answer"):
            print(f"[ModelAnswerBuilder] Skipping '{label}' — already extracted via vision.", flush=True)
            continue

        print(f"[ModelAnswerBuilder] Processing chunk {i+1}/{len(answer_chunks)}: '{label}' ({len(chunk_text)} chars)...", flush=True)
        partial = extract_answers_from_chunk(chunk_text, question_schema, label, i + 1, len(answer_chunks))
        if partial:
            partial_results.append(partial)

        if i < len(answer_chunks) - 1:
            time.sleep(1)

    final_schema = merge_answer_results(final_schema, partial_results)
    print(f"[ModelAnswerBuilder] Merged {len(partial_results)} text chunks into schema.", flush=True)

    return final_schema


# ─────────────────────────────────────────────────────────────
# Legacy alias (for code that calls split_into_chunks directly)
# ─────────────────────────────────────────────────────────────
def split_into_chunks(solution_text: str) -> list:
    """Legacy alias → now delegates to semantic chunking, returns just text portions."""
    semantic = split_into_semantic_chunks(solution_text)
    return [text for _, text in semantic]
