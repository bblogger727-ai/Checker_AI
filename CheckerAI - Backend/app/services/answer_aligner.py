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
        discovered = discovery_data.get("discovered_answers", [])
        
        print(f"[Aligner] Pass 1 complete: Found {len(discovered)} answer blocks.", flush=True)
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
3. **CONTENT MATCHING (CRITICAL for unlabeled answers)**: If the label is missing, unknown, or ambiguous:
   - Read the answer's CONTENT carefully.
   - Compare the TOPIC, ENTITIES, and KEYWORDS in the answer against each schema question.
   - The answer MUST topically match the question it is mapped to.
   - Example: Answer about "Puja Ltd" or "Poorva Impex" tax computation → schema B-Q1 asks about "Poorva Impex Ltd" → map to B-Q1.
   - Example: Answer about "YVPAY Bank" discount on bills → schema B-Q2-a asks about "YVPAY Bank" → map to B-Q2-a.
   - Example: Answer about "maintenance service" or "car hire" or "raw cotton" → these are items in B-Q1 (Poorva Impex) → map to B-Q1.
   - **NEVER map an answer to a question whose topic is completely different.**
4. **Subparts**: If a discovered answer contains subparts (a, b, c), map each subpart to the correct schema subpart ID.
5. **No match**: If you cannot confidently match an answer to any question, set question_id to "UNMAPPED".

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
    
    # ======================== INJECT INTO SCHEMA ========================
    _inject_answers(schema, answers_map)
    
    return schema


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
            # Check if this node is a question (has 'question' or 'question_text' AND 'marks')
            if ("question" in node or "question_text" in node) and "marks" in node:
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
                    "marks": node.get("marks", 0)
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
    """
    def _section_prefix(section_key: str) -> str:
        if section_key.startswith("Section"):
            return section_key.replace("Section", "")
        return section_key
    
    def _walk(node, path_parts=None):
        if path_parts is None:
            path_parts = []
        
        if isinstance(node, dict):
            # Check if this is a question node
            if ("question" in node or "question_text" in node) and "marks" in node:
                # Try explicit question_id first
                explicit_qid = node.get("question_id")
                # Construct path-based ID
                constructed_qid = "-".join([_section_prefix(p) for p in path_parts]) if path_parts else None
                
                # Try to match
                matched_qid = None
                if explicit_qid and explicit_qid in answers_map:
                    matched_qid = explicit_qid
                elif constructed_qid and constructed_qid in answers_map:
                    matched_qid = constructed_qid
                
                if matched_qid:
                    node["student_answer"] = answers_map[matched_qid]["student_answer"]
                    node["answer_pages"] = answers_map[matched_qid]["answer_pages"]
                elif "student_answer" not in node:
                    node["student_answer"] = ""
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

