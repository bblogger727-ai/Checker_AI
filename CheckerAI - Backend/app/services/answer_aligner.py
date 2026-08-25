"""
Answer Alignment Service — Two-Pass System

Pass 1: DISCOVERY — Identify all distinct answer blocks in the OCR text
Pass 2: MAPPING  — Map each discovered answer to the correct schema question

Handles:
- Answers written in any order
- MCQ detection (option letters near question numbers)
- Missing question labels (matches by content)
- Subpart detection (a, b, c within a question)
"""

from app.core.openai_client import client
import json


import re

def is_header_only_block(text: str) -> bool:
    if not text or not text.strip():
        return True
    cleaned = re.sub(
        r'^\s*(?:Ans\.?|Answer|Soln\.?|Solution|Q|Question)\s*[#\s\-\.\)]*\d+[\s\.\-\)]*[a-zA-Z]?\s*\)?\s*',
        '',
        text.strip(),
        flags=re.IGNORECASE
    ).strip()
    cleaned = re.sub(r'^\s*\(?[0-9]+[a-zA-Z]?\)?\s*', '', cleaned).strip()
    words = [w for w in re.sub(r'[^a-zA-Z0-9]', ' ', cleaned).split() if len(w) > 1]
    return len(words) < 5


def align_answers_to_schema(student_pages: list, schema: dict) -> dict:
    """
    Two-pass alignment of student answers to schema.
    
    Pass 1: Send all OCR text → discover answer blocks
    Pass 2: Send discovered blocks + schema → map to question IDs
    """
    
    # Build full OCR text with page markers
    full_text = "\n\n".join([f"[Page {p['page']}]\n{p['text']}" for p in student_pages])
    total_pages = len(student_pages)
    
    print(f"[Aligner] Starting two-pass alignment on {total_pages} pages...", flush=True)
    
    # ======================== PASS 1: DISCOVERY ========================
    print(f"[Aligner] Pass 1: Discovering answer blocks...", flush=True)
    
    discovery_prompt = f"""You are a precise exam answer sheet reader.

You are given the COMPLETE OCR text of a student's answer sheet ({total_pages} pages).

Your task is to identify EVERY DISTINCT answer the student has written.

INSTRUCTIONS:
1. Read through ALL the text carefully.
2. Identify each separate answer the student wrote. Look for:
   - Question numbers/labels: "Q1", "Ans 2", "1.", "(a)", "Question 3", etc.
   - MCQ answers: single option letters (a/b/c/d) or short option text near a question number
   - Descriptive answers: paragraphs, calculations, tables
   - Subparts: (a), (b), (c), (i), (ii), etc. within a larger question
   
3. For MCQ sections: Students typically write just the option letter. Group consecutive MCQ answers together.

4. For each answer block found, note:
   - Any question label/number visible
   - The page(s) it appears on
   - A brief content summary (first 200 chars)
   - Whether it looks like an MCQ answer or descriptive/calculation answer

5. Answers may NOT be in order. A student might write Q5 before Q2.

6. If text looks like it continues from a previous page (mid-sentence, continuation of a table), merge it with the earlier block.

7. IGNORE BLANK QUESTION HEADINGS: If a student wrote only a question label (e.g., 'Ans. 4b', 'Soln to Q4b', 'Q3a', '4) b)') and left the section blank with no answer text, IGNORE IT completely.

LABEL NORMALIZATION (CRITICAL):
- Handwritten labels are often OCR'd with errors. Common mistranscriptions of "Ans" include:
  "Aug", "Quy", "Day", "day", "ay", "an", "Key", "Try", "an.", "aug."
- Common mistranscriptions of question numbers: "7" → "9" or "?", "1" → "l" or "I"
- Common mistranscriptions of sub-part letters: "(a)" → "(9)", "la", "[a]"
- RULE: If text at the TOP of an answer block looks like it COULD be a question label
  (short line, followed by paragraphs or calculations), treat it as a label.
- In the "label" field of your output, output the NORMALIZED label using standard form:
  "Ans X(y)" or "Q X(y)" — e.g., "[day 7. (9)]" → label "Ans 7(a)", "[Quy 7 (b)]" → label "Ans 7(b)"
- If you cannot confidently normalize, output the raw text as-is.

STUDENT OCR TEXT:
{full_text}

OUTPUT JSON FORMAT:
{{
  "discovered_answers": [
    {{
      "label": "Q1" or "MCQ-1" or "unknown",
      "answer_type": "mcq" | "descriptive" | "calculation",
      "pages": [1, 2],
      "content_preview": "First 200 chars of the answer...",
      "full_content": "Complete answer text exactly as found in OCR"
    }}
  ]
}}

CRITICAL RULES:
- Include ALL answers you find, even if you're unsure which question they belong to.
- For MCQs, each individual MCQ answer should be a separate entry (e.g., MCQ-1, MCQ-2, etc.)
- Do NOT skip any text that looks like an answer.
- Do NOT modify or clean up the text — preserve it exactly as OCR extracted it, including tables.
- If multiple answers appear on the same page, split them into separate entries.
- In the label field only, normalize garbled headings into standard Ans X(y) format.
"""


    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a precise document analysis assistant. Extract all answer blocks from the OCR text."},
                {"role": "user", "content": discovery_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0
        )
        
        discovery_text = response.choices[0].message.content.strip()
        discovery_data = json.loads(discovery_text)
        discovered_raw = discovery_data.get("discovered_answers", [])
        
        discovered = []
        for d in discovered_raw:
            fc = d.get("full_content", "") or d.get("content_preview", "")
            if is_header_only_block(fc):
                print(f"[Aligner] ⊘ IGNORED header-only block: label={d.get('label')}, pages={d.get('pages')}", flush=True)
            else:
                discovered.append(d)

        print(f"[Aligner] Pass 1 complete: Found {len(discovered)} valid answer blocks.", flush=True)
        for i, d in enumerate(discovered):
            print(f"  [{i+1}] Label: {d.get('label', '?')}, Type: {d.get('answer_type', '?')}, Pages: {d.get('pages', [])}", flush=True)
            
    except Exception as e:
        print(f"[Aligner] Pass 1 ERROR: {e}", flush=True)
        discovered = []
    
    if not discovered:
        print("[Aligner] No answers discovered. Returning empty schema.", flush=True)
        return schema
    
    # ======================== PASS 2: MAPPING ========================
    print(f"[Aligner] Pass 2: Mapping {len(discovered)} answers to schema...", flush=True)
    
    # Build a compact schema summary for the mapping prompt
    schema_summary = _build_schema_summary(schema)
    
    mapping_prompt = f"""You are a precise exam alignment assistant.

You have two inputs:
1. A list of DISCOVERED ANSWERS from a student's answer sheet
2. The official QUESTION SCHEMA with all question IDs

Your task is to MAP each discovered answer to the correct question_id in the schema.

QUESTION SCHEMA (with question IDs, topics, and keywords):
{json.dumps(schema_summary, indent=2)}

DISCOVERED ANSWERS:
{json.dumps(discovered, indent=2)}

MAPPING INSTRUCTIONS:
1. **MCQ answers**: Map to the corresponding MCQ number in the schema (MCQ-1, MCQ-2, etc. → A-MCQ-1, A-MCQ-2, etc.)
2. **Labeled answers**: If the answer has a clear question label (Q1, Q2, etc.), match to the schema's question with that number.
3. **GARBLED LABELS — IMPORTANT**: Handwritten labels are often OCR-mistranscribed. Common patterns:
   - "day 7", "aug 7", "quy 7", "key 7" all likely mean "Ans 7" (question 7)
   - "(9)" or "(l)" after a number likely means "(a)" (sub-part a)
   - If a label LOOKS like it could be a question number, treat it as one.
   - **Always verify by checking the CONTENT of the answer** — if the answer content matches the schema question at that number, confirm the mapping.
4. **CONTENT MATCHING (CRITICAL for unlabeled or garbled answers)**: If the label is missing, unknown, or ambiguous:
   - Read the answer's CONTENT carefully.
   - Compare the TOPIC, ENTITIES, and KEYWORDS in the answer against each schema question.
   - The answer MUST topically match the question it is mapped to.
   - Example: Answer about "Puja Ltd" or "Poorva Impex" tax computation → schema B-Q1 asks about "Poorva Impex Ltd" → map to B-Q1.
   - Example: Answer about "YVPAY Bank" discount on bills → schema B-Q2-a asks about "YVPAY Bank" → map to B-Q2-a.
   - **NEVER map an answer to a question whose topic is completely different.**
5. **Subparts (CRITICAL)**: If a discovered answer block contains multiple subparts (a, b, c), you MUST produce SEPARATE mapping entries for each subpart:
   - Create one mapping entry for the (a) subpart and one for the (b) subpart, etc.
   - Each entry maps the SAME discovered_index but to the correct sub-part question_id.
   - Example: A single block containing "a) ... b) ..." → two entries: one for B-Q4-Q4a and one for B-Q4-Q4b.
   - This is essential: do NOT map the whole block to just the (a) subpart and leave (b) unmapped.
6. **No match**: If you cannot confidently match an answer to any question, set question_id to "UNMAPPED".

OUTPUT JSON FORMAT:
{{
  "mappings": [
    {{
      "discovered_index": 0,
      "question_id": "A-MCQ-1",
      "confidence": 0.95,
      "reason": "Label matches MCQ 1"
    }}
  ]
}}

CRITICAL RULES:
- Each discovered answer should map to AT MOST one question_id.
- Multiple discovered answers CAN map to the same question_id (they'll be merged).
- Use the EXACT question_id from the schema. Do not invent new IDs.
- Prioritize label matching over content matching when both are available.
- **VERIFY CONTENT**: Even if a label seems to match, verify the answer content relates to that question.
- **UNLABELED ANSWERS**: Many answers have label "unknown". You MUST use content matching for these. Read the schema keywords carefully.
- **GARBLED LABELS**: When the label looks like a mangled version of a question number (e.g., "day 7", "aug 7"), check the question content — if it matches, map it.
"""


    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a precise alignment assistant. Map discovered answers to the correct schema question IDs."},
                {"role": "user", "content": mapping_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0
        )
        
        mapping_text = response.choices[0].message.content.strip()
        mapping_data = json.loads(mapping_text)
        mappings = mapping_data.get("mappings", [])
        
        print(f"[Aligner] Pass 2 complete: {len(mappings)} mappings created.", flush=True)
        
    except Exception as e:
        print(f"[Aligner] Pass 2 ERROR: {e}", flush=True)
        mappings = []
    
    # ======================== BUILD ANSWER MAP ========================
    answers_map = {}
    
    for mapping in mappings:
        idx = mapping.get("discovered_index", -1)
        qid = mapping.get("question_id", "UNMAPPED")
        confidence = mapping.get("confidence", 0)
        
        if qid == "UNMAPPED" or idx < 0 or idx >= len(discovered):
            continue
        
        answer_block = discovered[idx]
        answer_text = answer_block.get("full_content", answer_block.get("content_preview", ""))
        answer_pages = answer_block.get("pages", [])
        
        if qid not in answers_map:
            answers_map[qid] = {
                "question_id": qid,
                "student_answer": answer_text,
                "answer_pages": answer_pages,
                "confidence": confidence
            }
        else:
            # Merge: append text, union pages
            answers_map[qid]["student_answer"] += "\n\n" + answer_text
            answers_map[qid]["answer_pages"] = sorted(list(set(
                answers_map[qid]["answer_pages"] + answer_pages
            )))
            answers_map[qid]["confidence"] = min(answers_map[qid]["confidence"], confidence)
    
    # ======================== MCQ SPLITTING ========================
    # If grouped MCQ answers exist (e.g., A-MCQ-1 contains "1) a 2) a 3) d ..."),
    # split them into individual MCQ entries
    answers_map = _split_grouped_mcqs(answers_map)
    
    # ======================== MCQ ANSWER CLEANING ========================
    # Strip number prefixes from MCQ answers: "1) a" → "a", "10) d" → "d"
    import re as _re
    for qid in answers_map:
        if "MCQ" in qid.upper():
            raw_ans = answers_map[qid]["student_answer"].strip()
            # Extract just the option letter from patterns like "1) a", "1. a", "(a)"
            match = _re.search(r'(?:\d+\s*[).\]]\s*)?[\(]?([a-dA-D])[\)]?', raw_ans)
            if match:
                answers_map[qid]["student_answer"] = match.group(1).lower()
    
    print(f"[Aligner] Final answer map: {len(answers_map)} unique question IDs mapped.", flush=True)
    for qid, data in answers_map.items():
        preview = data["student_answer"][:80].replace("\n", " ")
        print(f"  {qid}: Pages {data['answer_pages']} | {preview}...", flush=True)
    
    # ======================== PAGE SANITIZATION ========================
    def _sanitize_pages(full_text: str, pages: list) -> list:
        if not full_text or not student_pages:
            return pages
        lines = [
            l.strip() for l in full_text.split('\n')
            if len(l.strip()) > 10
            and not _re.search(r'^(?:classmate|date|page|audit test|test-\d+)', l.strip(), _re.IGNORECASE)
            and not _re.search(r'^[\s\|\-\:]+$', l.strip())  # skip markdown table separator lines like |---|---|
        ]
        if not lines:
            return pages
        real_pages = []
        for p in student_pages:
            p_num = p.get('page')
            p_text = p.get('text', '')
            if p_num and any(line[:25].lower() in p_text.lower() for line in lines):
                real_pages.append(p_num)
        return real_pages if real_pages else pages

    for qid in answers_map:
        answers_map[qid]["answer_pages"] = _sanitize_pages(
            answers_map[qid]["student_answer"], answers_map[qid]["answer_pages"]
        )

    # ======================== SIBLING SUB-PART SPLITTING ========================
    # When Q4a and Q4b both got mapped to the same text block and the same pages
    # (student wrote them continuously without a page break), split both the text
    # and the page list between the sibling sub-parts so each gets its own correct
    # answer text and page numbers.
    answers_map = _split_sibling_subparts(answers_map, student_pages)

    # ======================== INJECT INTO SCHEMA ========================
    _inject_answers(schema, answers_map)
    
    return schema


def _split_sibling_subparts(answers_map: dict, student_pages: list) -> dict:
    """
    Fix: when sibling sub-parts (Q4a / Q4b) share identical student_answer text
    and identical answer_pages, split both the text AND the page list between them.

    This happens when:
      - The LLM mapper correctly maps one discovered block to BOTH Q4a and Q4b
        (producing two mapping entries for the same discovered_index), AND
      - The two entries end up merged (same text, same pages) in answers_map.

    Strategy
    --------
    1. Group all non-MCQ question IDs by (sorted answer_pages, first-200-chars of text).
    2. If a group has ≥ 2 siblings, identify the natural boundary inside the shared text:
       look for sub-part markers like "b)", "(b)", "b.", "ii)" etc.
    3. Split the text at that boundary.
    4. Re-derive each sibling's pages by scanning the student_pages OCR for
       representative lines from each text slice.
    5. Ensure no two siblings share the same page list after splitting.
       If page re-derivation fails, fall back to: first sibling = first half of
       pages, second sibling = last half of pages (at minimum the last page).
    """
    import re as _re

    def _norm_key(entry: dict) -> tuple:
        pages_key = tuple(sorted(entry.get("answer_pages", [])))
        text_key  = (entry.get("student_answer") or "")[:200].strip()
        return (pages_key, text_key)

    def _sub_part_letter(q_id: str) -> str | None:
        """Extract trailing sub-part letter/number from a question ID.
        e.g. 'Q4b' → 'b', 'B-Q4-Q4b' → 'b', 'Q3a' → 'a'
        """
        m = _re.search(r'[Qq]\d+([a-z])', q_id)
        return m.group(1) if m else None

    # Build collision groups: norm_key → [qid, ...]
    collision_groups: dict[tuple, list[str]] = {}
    for qid, entry in answers_map.items():
        if "MCQ" in qid.upper():
            continue
        k = _norm_key(entry)
        if k[0]:  # only if has pages
            collision_groups.setdefault(k, []).append(qid)

    # Build a flat page-text lookup for page re-derivation
    page_text_lookup: dict[int, str] = {
        p["page"]: p.get("text", "")
        for p in student_pages
        if isinstance(p.get("page"), int)
    }

    for (pages_key, _), siblings in collision_groups.items():
        if len(siblings) < 2:
            continue

        # Sort siblings by their sub-part letter so 'a' < 'b' < 'c'
        siblings_sorted = sorted(
            siblings,
            key=lambda q: (_sub_part_letter(q) or q)
        )

        print(
            f"[Aligner] ⚡ Sibling collision: {siblings_sorted} all share pages "
            f"{list(pages_key)} — attempting text+page split",
            flush=True,
        )

        shared_text = answers_map[siblings_sorted[0]]["student_answer"]
        shared_pages = list(pages_key)

        # ── Build split points using sub-part boundary patterns ────────────
        # We look for the start of the SECOND sub-part onwards.
        # Pattern covers: "b)", "b.", "(b)", "b )", "B)", "ii)", "(ii)",
        # plus common OCR garbles.
        split_positions: list[tuple[int, str]] = []  # (char_index, subpart_label)

        for i, qid in enumerate(siblings_sorted[1:], start=1):
            letter = _sub_part_letter(qid)
            if not letter:
                continue
            # Roman numeral equivalent for (a)=i (b)=ii (c)=iii
            roman = ["i", "ii", "iii", "iv", "v"][ord(letter) - ord("a")] if ord(letter) - ord("a") < 5 else letter

            # ── Priority 1: direct letter patterns (b), (b), b. ──────────────
            # These are tried FIRST and win exclusively if any match exists.
            # This prevents Q4a's internal sub-labels (e.g. "ii)") from being
            # mistaken for the Q4b boundary.
            direct_patterns = [
                rf'(?<!\w){_re.escape(letter)}\s*\)',    # b)
                rf'\(\s*{_re.escape(letter)}\s*\)',      # (b)
                rf'(?<!\w){_re.escape(letter)}\.',       # b.
            ]
            # ── Priority 2: roman numerals — fallback only ────────────────────
            roman_patterns = [
                rf'(?<!\w){_re.escape(roman)}\)',        # ii)
                rf'\(\s*{_re.escape(roman)}\s*\)',       # (ii)
                rf'(?<!\w){_re.escape(roman)}\.',        # ii.
            ]

            best_pos = None
            # Try direct patterns first
            for pat in direct_patterns:
                for m in _re.finditer(pat, shared_text, _re.IGNORECASE):
                    pos = m.start()
                    if pos < 30:
                        continue
                    if best_pos is None or pos < best_pos:
                        best_pos = pos

            # Only try roman numerals if NO direct match was found
            if best_pos is None:
                for pat in roman_patterns:
                    for m in _re.finditer(pat, shared_text, _re.IGNORECASE):
                        pos = m.start()
                        if pos < 30:
                            continue
                        if best_pos is None or pos < best_pos:
                            best_pos = pos

            if best_pos is not None:
                split_positions.append((best_pos, letter))

        if not split_positions:
            print(
                f"  [Aligner] ⚠ Could not find sub-part boundary in shared text — "
                f"falling back to page-halving for {siblings_sorted}",
                flush=True,
            )
            # Fallback: distribute pages evenly
            chunk = max(1, len(shared_pages) // len(siblings_sorted))
            for idx, qid in enumerate(siblings_sorted):
                start = idx * chunk
                end = start + chunk if idx < len(siblings_sorted) - 1 else len(shared_pages)
                sub_pages = shared_pages[start:end] or [shared_pages[-1]]
                answers_map[qid]["answer_pages"] = sub_pages
                print(f"  → {qid}: pages {sub_pages} (halved)", flush=True)
            continue

        # ── Build text slices from split positions ──────────────────────────
        split_positions.sort(key=lambda x: x[0])
        boundaries = [0] + [pos for pos, _ in split_positions] + [len(shared_text)]
        text_slices = [
            shared_text[boundaries[i]:boundaries[i + 1]].strip()
            for i in range(len(boundaries) - 1)
        ]
        # Pad if fewer slices than siblings
        while len(text_slices) < len(siblings_sorted):
            text_slices.append("")

        # ── Anchor-based page assignment ──────────────────────────────────────
        # For each split boundary, find which physical page the new sub-part
        # STARTS on by scanning each page's OCR for the first distinct line
        # of the new sub-part's text.  This is far more reliable than fuzzy
        # line-matching because we only look at the OPENING lines (where the
        # sub-part label like "b)" appears), not all representative lines.
        #
        # Rules after finding split_start_page for Q4b:
        #   Q4a = shared_pages[:split_start_page_idx + 1]   (Q4a ends mid that page)
        #   Q4b = shared_pages[split_start_page_idx:]       (Q4b starts on that page)
        # Page ordering is preserved; both legitimately include the boundary page.

        def _find_start_page(slice_text: str) -> int | None:
            """Return the shared_pages entry where slice_text first appears."""
            if not slice_text:
                return None
            # Use the first 3 non-trivial lines of the slice as anchors
            anchors = [
                l.strip()[:35].lower()
                for l in slice_text.split("\n")
                if len(l.strip()) > 8
            ][:3]
            if not anchors:
                return None
            for pg in shared_pages:
                pg_text = page_text_lookup.get(pg, "").lower()
                if any(a in pg_text for a in anchors):
                    return pg
            return None

        # Build split-page boundaries: for each later sibling, find the page
        # their sub-part text starts on.
        # split_page_starts[i] = the page where siblings_sorted[i] (i>=1) starts
        split_page_starts: list[int | None] = [None]  # index 0 (first sibling) always starts on shared_pages[0]
        for i in range(1, len(siblings_sorted)):
            sp = _find_start_page(text_slices[i])
            split_page_starts.append(sp)
            print(
                f"  [Aligner] 📍 {siblings_sorted[i]} boundary text starts on page {sp}",
                flush=True,
            )

        for idx, qid in enumerate(siblings_sorted):
            slice_text = text_slices[idx]

            if idx == 0:
                # First sibling: starts at shared_pages[0].
                # Ends on the page BEFORE the next sibling starts — but since the
                # next sibling may START mid-page (the student wrote both on the
                # same physical page), we INCLUDE that boundary page in Q4a too.
                next_start_page = split_page_starts[1] if len(split_page_starts) > 1 else None
                if next_start_page and next_start_page in shared_pages:
                    boundary_idx = shared_pages.index(next_start_page)
                    derived_pages = shared_pages[:boundary_idx + 1]  # include boundary page
                else:
                    derived_pages = shared_pages  # fallback
            else:
                # Later sibling: starts on its detected start page, ends at end of shared_pages
                my_start_page = split_page_starts[idx]
                if my_start_page and my_start_page in shared_pages:
                    start_idx = shared_pages.index(my_start_page)
                    derived_pages = shared_pages[start_idx:]
                else:
                    # Fallback: positional split
                    chunk = max(1, len(shared_pages) // len(siblings_sorted))
                    start = idx * chunk
                    derived_pages = shared_pages[start:] or [shared_pages[-1]]

            answers_map[qid]["student_answer"] = slice_text
            answers_map[qid]["answer_pages"]   = derived_pages
            print(

                f"  [Aligner] ✂ {qid}: text_len={len(slice_text)}, pages={derived_pages}",
                flush=True,
            )

    return answers_map


def _split_grouped_mcqs(answers_map: dict) -> dict:
    """
    Split grouped MCQ answers into individual entries.
    
    Example: A-MCQ-1 = "1) a 2) a 3) d 4) a 5) a"
    → A-MCQ-1 = "a", A-MCQ-2 = "a", A-MCQ-3 = "d", A-MCQ-4 = "a", A-MCQ-5 = "a"
    """
    import re
    
    mcq_keys = [k for k in answers_map if "MCQ" in k.upper()]
    
    if not mcq_keys:
        return answers_map
    
    new_entries = {}
    keys_to_remove = []
    
    for mcq_key in mcq_keys:
        answer_text = answers_map[mcq_key]["student_answer"]
        answer_pages = answers_map[mcq_key]["answer_pages"]
        
        # Try to parse individual MCQ answers from grouped text
        # Patterns: "1) a", "1. a", "1) (a)", "1. (a)"
        matches = re.findall(r'(\d+)\s*[).\]]\s*\(?([a-dA-D])\)?', answer_text)
        
        if len(matches) > 1:
            # This is a grouped answer — split it
            print(f"[Aligner] Splitting grouped MCQ {mcq_key}: found {len(matches)} individual answers", flush=True)
            keys_to_remove.append(mcq_key)
            
            # Determine the section prefix (e.g., "A-MCQ-")
            # Extract prefix: "A-MCQ-1" → "A-MCQ-"
            prefix_match = re.match(r'(.+-MCQ-)\d+', mcq_key)
            if prefix_match:
                prefix = prefix_match.group(1)
            else:
                prefix = "A-MCQ-"
            
            for num_str, option in matches:
                individual_key = f"{prefix}{num_str}"
                new_entries[individual_key] = {
                    "question_id": individual_key,
                    "student_answer": option.lower(),
                    "answer_pages": answer_pages,
                    "confidence": 0.9
                }
                print(f"  → {individual_key}: {option.lower()}", flush=True)
    
    # Remove grouped entries, add individual ones
    for k in keys_to_remove:
        del answers_map[k]
    
    answers_map.update(new_entries)
    
    return answers_map


def _build_schema_summary(schema: dict) -> list:
    """
    Build a compact summary of the schema for the mapping prompt.
    Constructs question_id from schema path if not explicitly set.
    Returns a list of {question_id, question_preview, keywords, section} entries.
    """
    summaries = []
    
    def _extract_keywords(text: str) -> list:
        """Extract key entities and topic words from question text."""
        import re
        words = re.findall(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*', text)
        terms = []
        for kw in ['GST', 'CGST', 'SGST', 'IGST', 'ITC', 'TCS', 'TDS', 'customs',
                   'import', 'export', 'refund', 'appeal', 'assessment', 'baggage',
                   'maintenance', 'car hire', 'raw cotton', 'metal scrap', 'bank',
                   'income tax', 'compounding', 'summons', 'installment', 'revision',
                   'status holder', 'foreign trade', 'depreciation', 'profit', 'loss',
                   'balance sheet', 'cash flow', 'goodwill', 'amalgamation', 'debenture',
                   'shares', 'dividend', 'bonus', 'right issue']:
            if kw.lower() in text.lower():
                terms.append(kw)
        all_kw = list(set(words[:10] + terms[:10]))
        return all_kw[:15]
    
    def _section_prefix(section_key: str) -> str:
        """Convert SectionA → A, SectionB → B, etc."""
        if section_key.startswith("Section"):
            return section_key.replace("Section", "")
        return section_key
    
    def _scan(node, path_parts=None):
        if path_parts is None:
            path_parts = []
        
        if isinstance(node, dict):
            # Check if this node is a question
            # Supports: marks, max_marks, marks_total (used in grading_final.json)
            has_marks = any(k in node for k in ("marks", "max_marks", "marks_total", "marks_obtained"))
            if ("question" in node or "question_text" in node) and has_marks:
                # Use explicit question_id if available, else construct from path
                explicit_qid = node.get("question_id")
                if explicit_qid:
                    qid = explicit_qid
                else:
                    # Construct: e.g., ["SectionB", "Q1"] → "B-Q1"
                    # e.g., ["SectionB", "Q2", "a"] → "B-Q2-a"
                    # e.g., ["SectionA", "MCQ", "1"] → "A-MCQ-1"
                    qid = "-".join([_section_prefix(p) for p in path_parts])
                
                q_text = node.get("question") or node.get("question_text", "")
                summaries.append({
                    "question_id": qid,
                    "question_preview": q_text[:400],
                    "keywords": _extract_keywords(q_text),
                    "section": path_parts[0] if path_parts else "",
                    "marks": node.get("marks", node.get("max_marks", node.get("marks_total", 0)))
                })
            
            # Recurse into children
            for key, value in node.items():
                if key in ["question", "model_answer", "marks", "question_id",
                          "student_answer", "answer_pages", "or_group"]:
                    continue
                _scan(value, path_parts + [key])
        elif isinstance(node, list):
            for i, item in enumerate(node):
                _scan(item, path_parts + [str(i)])
    
    _scan(schema)
    return summaries


def _inject_answers(schema: dict, answers_map: dict):
    """
    Inject mapped answers into the schema structure.
    Walks the schema tree and matches by explicit question_id or by constructed path ID.
    Uses normalized key matching (ignoring hyphens, spaces, parens, case) to ensure reliable matches.
    """
    import re
    def _norm(s: str) -> str:
        if not s:
            return ""
        return re.sub(r'[^a-zA-Z0-9]', '', str(s)).lower()

    norm_answers_map = {}
    for map_k, map_v in answers_map.items():
        norm_k = _norm(map_k)
        if norm_k:
            norm_answers_map[norm_k] = map_v
        clean_k = re.sub(r'^[a-zA-Z]-', '', str(map_k))
        norm_clean = _norm(clean_k)
        if norm_clean:
            norm_answers_map[norm_clean] = map_v

    def _section_prefix(section_key: str) -> str:
        if section_key.startswith("Section"):
            return section_key.replace("Section", "")
        return section_key
    
    def _walk(node, path_parts=None):
        if path_parts is None:
            path_parts = []
        
        if isinstance(node, dict):
            # Check if this is a question node
            # Supports: marks, max_marks, marks_total, marks_obtained (various schema formats)
            has_marks = any(k in node for k in ("marks", "max_marks", "marks_total", "marks_obtained"))
            if ("question" in node or "question_text" in node) and has_marks:
                explicit_qid = node.get("question_id")
                constructed_qid = "-".join([_section_prefix(p) for p in path_parts]) if path_parts else None
                q_num = node.get("question_number")
                
                # Build candidate IDs to try matching against the answers_map
                candidates = []
                if explicit_qid:
                    candidates.append(explicit_qid)
                if constructed_qid:
                    candidates.append(constructed_qid)
                if path_parts:
                    # e.g. last path part is "Q1a" or "Q2b"
                    candidates.append(path_parts[-1])
                if q_num:
                    candidates.append(q_num)
                    candidates.append(f"Q{q_num}")

                # Normalized match: strip all non-alphanumeric so Q1a == Q-1(a) == q1a
                matched_val = None
                for cand in candidates:
                    norm_cand = _norm(cand)
                    if norm_cand and norm_cand in norm_answers_map:
                        matched_val = norm_answers_map[norm_cand]
                        break
                
                if matched_val:
                    node["student_answer"] = matched_val["student_answer"]
                    node["pages"] = matched_val["answer_pages"]
                    node["answer_pages"] = matched_val["answer_pages"]
                elif "student_answer" not in node:
                    node["student_answer"] = ""
                    node["pages"] = []
                    node["answer_pages"] = []
            
            # Recurse into children
            for key, value in node.items():
                if key in ["question", "model_answer", "marks", "question_id",
                          "student_answer", "answer_pages", "or_group"]:
                    continue
                if isinstance(value, (dict, list)):
                    _walk(value, path_parts + [key])
        elif isinstance(node, list):
            for i, item in enumerate(node):
                _walk(item, path_parts + [str(i)])
    
    _walk(schema)
