"""
Answer Alignment Service — Claude Sonnet 4 Version

Pass 1: DISCOVERY — Identify all distinct answer blocks in the OCR text using Claude
Pass 2: MAPPING  — Map each discovered answer to the correct schema question using Claude

Handles:
- Answers written in any order
- MCQ detection
- Missing question labels
- Subpart detection
"""

import os
import sys
import json
import re

# Setup path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import anthropic
from dotenv import load_dotenv

load_dotenv()

# Claude client
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
CLAUDE_MODEL = "claude-sonnet-4-6"

from app.services.answer_aligner import (
    _split_grouped_mcqs,
    _build_schema_summary,
    _inject_answers
)

from claude_grading.pipeline_utils import normalize_schema_structure

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


def align_answers_to_schema_claude(student_pages: list, schema: dict, manifest_questions: list = None) -> dict:
    """
    Two-pass alignment of student answers to schema using Claude Sonnet 4.
    manifest_questions: List of question IDs/numbers known to be answered (from student_marks.json)
    """
    manifest_str = ", ".join([str(q) for q in (manifest_questions or [])])
    
    # Build full OCR text with page markers
    full_text = "\n\n".join([f"[Page {p['page']}]\n{p['text']}" for p in student_pages])
    total_pages = len(student_pages)
    
    print(f"[Claude Aligner] Starting two-pass alignment on {total_pages} pages...", flush=True)
    
    # ======================== PASS 1: DISCOVERY ========================
    print(f"[Claude Aligner] Pass 1: Discovering answer blocks...", flush=True)
    
    discovery_prompt = f"""You are a precise exam answer sheet reader.

You are given the COMPLETE OCR text of a student's answer sheet ({total_pages} pages).

Your task is to identify EVERY DISTINCT answer the student has written, along with the TOPIC of each answer.

INSTRUCTIONS:
1. Read through ALL the text carefully.
2. Identify each separate answer the student wrote. Look for:
   - Explicit question labels: "Ans to Q2:", "Q3", "Ans 7", "(a)", etc.
   - MCQ answers: single option letters (a/b/c/d) near a question number
   - Descriptive/legal/calculation answers: paragraphs, tables, figures
   - Subparts: (a), (b), (c), (i), (ii) within a larger question

3. For EACH answer block, also extract a brief TOPIC SUMMARY — what concept, law, entity, or computation the answer is about. Examples:
   - "About composition scheme eligibility and tax rate"
   - "Computation of taxable value of supply"
   - "Principal-agent relationship under Schedule I"
   - "Reverse charge on sitting fees paid to director"
   This topic summary is CRITICAL for correct mapping later.

4. VERY IMPORTANT — DO NOT assume question number from page position:
   - A block on Page 1 with no label is NOT automatically Q1.
   - A student may skip questions and start with Q2, Q3, etc.
   - If a block has no explicit label, mark label as "unknown" and rely on topic summary for matching.
   - ONLY assign a label if the student explicitly wrote it (e.g., "Ans to Q3", "Q3.", "3)").

5. Answers may be in any order. A student might write Q5 before Q2.

6. If a page clearly continues mid-sentence from the previous, merge it with the earlier block.

STUDENT OCR TEXT:
{full_text}

OUTPUT JSON FORMAT:
{{
  "discovered_answers": [
    {{
      "label": "Q2" or "unknown",
      "answer_type": "mcq" | "descriptive" | "calculation",
      "pages": [1, 2],
      "topic_summary": "Brief description of what the answer is about (2-3 sentences)",
      "content_preview": "First 200 chars of the answer...",
      "full_content": "Complete answer text exactly as found in OCR"
    }}
  ]
}}

CRITICAL RULES:
- ZERO TEXT DROPPED: The combined `full_content` of all discovered blocks MUST EXACTLY equal the full input text. Every single sentence, table, heading, and number from every page MUST be included in some block.
- If text has no label and doesn't seem to fit a previous answer, create a new block with label "unknown". NEVER silently discard text.
- Label MUST reflect what the student ACTUALLY wrote, not your inference. If student didn't label it, use "unknown".
- Do NOT modify or clean up the text \u2014 preserve it exactly as OCR extracted it, including tables.
- If multiple labeled answers appear on the same page, split them into separate entries.
- Output ONLY valid JSON.
"""

    try:
        response = claude_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8192,
            system="You are a precise exam answer sheet reader. Your job is to identify every written answer and its topic, so it can later be matched to the correct schema question by content — NOT by page position. Output strictly in JSON format.",
            messages=[
                {"role": "user", "content": discovery_prompt}
            ],
            temperature=0
        )
        
        discovery_text = response.content[0].text.strip()
        discovery_data = _extract_json_from_claude(discovery_text)
        discovered = discovery_data.get("discovered_answers", [])
        
        print(f"[Claude Aligner] Pass 1 complete: Found {len(discovered)} answer blocks.", flush=True)
        for i, d in enumerate(discovered):
            print(f"  [{i+1}] Label: {d.get('label', '?')}, Type: {d.get('answer_type', '?')}, Pages: {d.get('pages', [])}", flush=True)
            
    except Exception as e:
        print(f"[Claude Aligner] Pass 1 ERROR: {e}", flush=True)
        discovered = []
    
    if not discovered:
        print("[Claude Aligner] No answers discovered. Returning empty schema.", flush=True)
        return schema
    
    # ======================== PASS 2: MAPPING ========================
    print(f"[Claude Aligner] Pass 2: Mapping {len(discovered)} answers to schema...", flush=True)
    
    schema_summary = _build_schema_summary(schema)
    
    # Build full schema summary with question text for semantic matching
    schema_for_mapping = _build_schema_summary(schema)
    print(f"[Claude Aligner] Schema summary for mapping: {json.dumps(schema_for_mapping, indent=2)}", flush=True)
    
    mapping_prompt = f"""You are a precise exam answer alignment assistant.

You have two inputs:
1. A list of DISCOVERED ANSWERS from a student's answer sheet (each with a topic_summary)
2. The official QUESTION SCHEMA with question IDs and the FULL question text
{"3. A MANIFEST of question numbers the student DEFINITELY answered: " + manifest_str if manifest_questions else ""}

Your task: MAP each discovered answer to the correct question_id(s) by MATCHING TOPICS AND CONTENT.

QUESTION SCHEMA:
{json.dumps(schema_for_mapping, indent=2)}

DISCOVERED ANSWERS:
{json.dumps(discovered, indent=2)}

MAPPING RULES (read carefully — this is the most important part):

### Rule 1 — EXPLICIT LABELS & HEURISTIC RECOVERY
- If the student explicitly labeled an answer (e.g., "Ans to Q1", "Q4(a)"), use it as the PRIMARY matching signal.
- **HEURISTIC RECOVERY**: If an explicit label (e.g., "Q2") leads to a block whose topic summary is COMPLETELY UNRELATED to the schema Q2, AND there is another block with "unknown" label that strongly matches Q2, OR there are duplicate "Q2" labels, you MUST use content matching to resolve the conflict. 
- **DUPLICATE LABEL STRATEGY**: If you see two different blocks with the same explicit label (e.g., two "Answer 8" blocks), it is GUARANTEED that one is mislabeled. You MUST ignore the labels for both these blocks and map them purely based on their `topic_summary` and `content_preview` matching against the schema.

### Rule 2 — DO NOT MAP 'UNKNOWN' BY POSITION
- A block on Page 1 is NOT automatically Q1. Students often skip questions and write them in a different order.
- If the label is "unknown" (no explicit label), you MUST determine the correct question_id purely by matching the content and topic_summary to the schema question text.

### Rule 3 — CONTENT MATCHING FOR UNKNOWN & MISLABELED BLOCKS
- Use content matching as the primary driver for "unknown" labels.
- Use content matching as a verification layer for explicit labels to catch student mislabeling (e.g., writing Q3 under a Q2 heading).

### Rule 4 — MULTI-SUBPART MAPPING
If one discovered block contains answers to multiple subparts (e.g., Q4(a) and Q4(b) are both there),
you MUST output a separate mapping entry for EACH question_id.

### Rule 5 — WHEN IN DOUBT, USE CONTENT
If an explicit label seems wrong based on the topic summary, favor the topic summary match if it aligns perfectly with another schema question.

### Rule 6 — PARENT LABEL → SUBPART IDs (MANDATORY AND CRITICAL)
Students often write "Ans to Q3" without specifying (a) or (b), or they write "Q4(a)" but answer the whole question.
In the schema, Q3/Q4 may ONLY have subpart IDs like `A-Q3-a` and `A-Q3-b`.
In this case: YOU MUST map the answer to ALL available subpart IDs of that parent question!
EVEN IF the student specified a specific subpart (like 'a'), you SHOULD check if the content ALSO covers other subparts. If in doubt, map to ALL subparts of that question number to ensure the grader sees the full context.

### MANDATORY OVERRIDE Rule (RECOVERY FOCUS)
1. <CRITICAL> If a block has an explicit label, start with that mapping. However, if the TOPIC SUMMARY of that block matches another question with >90% similarity (and is >90% dissimilar to the current label's question), MOVE the mapping to the correct question. 
2. If there are DUPLICATE explicit labels (e.g., two blocks labeled "Q2"), use content matching to determine which is Q2 and which is something else (usually a mislabeled Q3 or another missing question ID).
3. If a question is in the schema/manifest (e.g., Q6) but has NO explicit label match, and another question has a duplicate (e.g., two Q8s), check if one of those duplicates matches the missing question's topic. Reassign it.
4. <CRITICAL> **COVERAGE CHECK**: EVERY SINGLE DISCOVERED ANSWER MUST BE MAPPED to at least one question_id. There should be NO dropped blocks. If you truly cannot map an unknown block, map it to the most likely theoretical question or the last answered question, but do NOT ignore it.
### Rule 8 — MANIFEST ENFORCEMENT (NEW & CRITICAL)
The student DEFINITELY answered these questions: {manifest_str}.
You MUST find these answers in the DISCOVERED ANSWERS. If you see a block that MIGHT be one of these (even if labeled 'unknown' or mislabeled), prioritize mapping it to the manifest question.

### Rule 9 — QUESTION NUMBER OCR MISREADS
Students often label answers like 'Question 5' or 'Q5'. OCR might misread this as 'Question S' or 'QS'. Be highly aware of this OCR artifact and map 'Question S' to Q5. Same goes for similar character confusions.

OUTPUT JSON FORMAT (must be an array of mapping objects):
{{
  "mappings": [
    {{
      "discovered_index": 0,
      "question_id": "A-Q3-a",
      "confidence": 0.95,
      "reason": "Explicitly labeled as Q3, content matches goodwill impairment topic"
    }},
    {{
      "discovered_index": 0,
      "question_id": "A-Q3-b",
      "confidence": 0.95,
      "reason": "Mapped to subpart b as part of Q3 answer block"
    }}
  ]
}}


### Rule 7 — HANDLE ID PREFIXES (CRITICAL FOR MAPPING)
The schema question_ids may have prefixes like "PART I-Q1", "Section A-MCQ-1", or "B-Q3-a".
The student's label "Q1" will rarely include the "PART I-" prefix. Map it to the ID containing "Q1" in the current section.

FINAL REMINDERS:
- A single discovered answer CAN map to MULTIPLE question_ids (for subparts).
- Use EXACT question_id strings from the schema.
- Ensure 100% of the OCR text is accounted for by mapping all discovered blocks.
"""

    try:
        response = claude_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8192,
            system="You are an exam answer alignment expert. Your goal is to map student answers to the correct schema question IDs. While explicit labels are important, you MUST use content matching and topic summaries to catch cases where a student has mislabeled a question (e.g., writing 'Q2' but answering Q3), or where OCR has misread a label. Your primary goal is COMPLETE AND ACCURATE coverage. Output only valid JSON.",
            messages=[
                {"role": "user", "content": mapping_prompt}
            ],
            temperature=0
        )
        
        mapping_text = response.content[0].text.strip()
        mapping_data = _extract_json_from_claude(mapping_text)
        mappings = mapping_data.get("mappings", [])
        
        print(f"[Claude Aligner] Pass 2 complete: {len(mappings)} mappings created.", flush=True)
        if mappings:
            print(f"[Claude Aligner] Raw mappings from Claude: {json.dumps(mappings, indent=2)}", flush=True)
        
    except Exception as e:
        print(f"[Claude Aligner] Pass 2 ERROR: {e}", flush=True)
        mappings = []
    
    # ======================== BUILD ANSWER MAP ========================
    answers_map = {}
    
    for mapping in mappings:
        idx = mapping.get("discovered_index", -1)
        qid = mapping.get("question_id", "UNMAPPED")
        print(f"[Claude Aligner] Processing mapping: idx={idx}, qid='{qid}'", flush=True)
        if isinstance(idx, str) and idx.isdigit():
            idx = int(idx)
        # If Claude hallucinates 1-based indexing, fix it to 0-based
        if idx > 0 and idx == len(discovered):
            idx = idx - 1
            
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
            answers_map[qid]["student_answer"] += "\n\n" + answer_text
            answers_map[qid]["answer_pages"] = sorted(list(set(
                answers_map[qid]["answer_pages"] + answer_pages
            )))
            answers_map[qid]["confidence"] = min(answers_map[qid]["confidence"], confidence)
    
    # ======================== MCQ SPLITTING & CLEANING ========================
    answers_map = _split_grouped_mcqs(answers_map)
    
    for qid in answers_map:
        if "MCQ" in qid.upper():
            raw_ans = answers_map[qid]["student_answer"].strip()
            match = re.search(r'(?:\d+\s*[).\]]\s*)?[\(]?([a-dA-D])[\)]?', raw_ans)
            if match:
                answers_map[qid]["student_answer"] = match.group(1).lower()
    
    print(f"[Claude Aligner] Final answer map: {len(answers_map)} unique question IDs mapped.", flush=True)
    for qid, data in answers_map.items():
        preview = data["student_answer"][:80].replace("\n", " ")
        print(f"  {qid}: Pages {data['answer_pages']} | {preview}...", flush=True)
    
    # ======================== INJECT INTO SCHEMA ========================
    _inject_answers(schema, answers_map)
    
    # ── Final Robustness: Normalize structure ──────────────────────────
    print("[Claude Aligner] Normalizing schema structure...", flush=True)
    schema = normalize_schema_structure(schema)
    
    return schema
