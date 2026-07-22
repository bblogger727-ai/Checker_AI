#!/usr/bin/env python3
"""
CA Specialized Stage 4:
Aligns student answers to schema AND injects marks scored from student_marks.json.
"""
import os
import sys
import json
import argparse

pipeline_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(pipeline_dir, "..", "CheckerAI - Backend")
sys.path.insert(0, backend_dir)
from dotenv import load_dotenv
load_dotenv(os.path.join(backend_dir, ".env"))

from app.services.answer_parser import parse_ocr_to_pages
from claude_grading.answer_aligner_claude import align_answers_to_schema_claude

def inject_marks_into_schema(schema, marks_dict):
    """
    Recursively inject marks_scored into the schema.
    Also propagates 'marks' (total) if missing but available elsewhere.
    """
    marks_scored_map = marks_dict.get("marks", {})
    
    def normalize_key(k):
        if not k: return ""
        k = str(k).split("-")[-1]
        if k.startswith('Q'): k = k[1:]
        return k.lower().strip()

    # 1. Build a map of total marks from nodes that have them
    total_marks_map = {}
    def _collect_totals(node):
        if isinstance(node, dict):
            qid = node.get("question_id")
            qnum = node.get("question_number")
            subpart = node.get("subpart")
            m = node.get("marks")
            if m is not None:
                for k in [normalize_key(qid), normalize_key(subpart), normalize_key(qnum)]:
                    if k and k not in total_marks_map:
                        total_marks_map[k] = m
            for v in node.values(): _collect_totals(v)
        elif isinstance(node, list):
            for i in node: _collect_totals(i)
            
    _collect_totals(schema)

    # 2. Normalized scored marks
    norm_scored = {normalize_key(k): v for k, v in marks_scored_map.items()}

    def _inject(node):
        if not isinstance(node, dict):
            return
            
        qid = node.get("question_id")
        qnum = node.get("question_number")
        subpart = node.get("subpart")
        
        keys_to_try = []
        if qid: keys_to_try.append(normalize_key(qid))
        if subpart: keys_to_try.append(normalize_key(subpart))
        if qnum and subpart: keys_to_try.append(normalize_key(f"{qnum}{subpart}"))
        if qnum and not subpart: keys_to_try.append(normalize_key(qnum))
            
        # Inject total marks if missing
        if node.get("marks") is None:
            for k in keys_to_try:
                if k in total_marks_map:
                    node["marks"] = total_marks_map[k]
                    break

        # Inject marks scored and allotted
        for k in keys_to_try:
            if k in norm_scored:
                val = norm_scored[k]
                if isinstance(val, dict):
                    if val.get("scored") is not None:
                        node["marks_scored"] = val.get("scored")
                    if val.get("allotted") is not None:
                        node["marks"] = val.get("allotted")
                    print(f"[CA Mark Injection] Injected {val.get('scored')}/{val.get('allotted')} marks into {qid or qnum} (via {k})")
                else:
                    node["marks_scored"] = val
                    print(f"[CA Mark Injection] Injected {val} marks into {qid or qnum} (via {k})")
                break
                
        for v in node.values():
            if isinstance(v, dict):
                _inject(v)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        _inject(item)
                
    _inject(schema)

def propagate_answers_in_schema(schema):
    """
    Ensure that if any node has a student_answer, all other nodes representing 
    the same question_number/subpart also get that answer.
    """
    answer_pool = {} # normalized_key -> {text, pages}
    
    def normalize_key(k):
        if not k: return ""
        k = str(k).split("-")[-1]
        if k.startswith('Q'): k = k[1:]
        return k.lower().strip()

    def _collect(node):
        if isinstance(node, dict):
            ans = node.get("student_answer")
            if ans and len(str(ans).strip()) > 0:
                qid = node.get("question_id")
                qnum = node.get("question_number")
                subp = node.get("subpart")
                for k in [normalize_key(qid), normalize_key(qnum), normalize_key(subp)]:
                    if k and k not in answer_pool:
                        answer_pool[k] = {
                            "text": ans,
                            "pages": node.get("answer_pages", [])
                        }
            for v in node.values(): _collect(v)
        elif isinstance(node, list):
            for i in node: _collect(i)
            
    _collect(schema)
    
    def _apply(node):
        if isinstance(node, dict):
            if not node.get("student_answer"):
                qid = node.get("question_id")
                qnum = node.get("question_number")
                subp = node.get("subpart")
                for k in [normalize_key(qid), normalize_key(qnum), normalize_key(subp)]:
                    if k in answer_pool:
                        node["student_answer"] = answer_pool[k]["text"]
                        node["answer_pages"] = answer_pool[k]["pages"]
                        break
            for v in node.values(): _apply(v)
        elif isinstance(node, list):
            for i in node: _apply(i)
            
    _apply(schema)

def main():
    parser = argparse.ArgumentParser(description='CA Specialized Answer Alignment')
    parser.add_argument('--dataset', required=True, help='Dataset ID')
    
    args = parser.parse_args()
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dataset_dir = os.path.join(base_dir, "feedback_results", f"dataset_{args.dataset}")
    
    schema_path = os.path.join(dataset_dir, "schema_with_answers.json")
    ocr_path = os.path.join(dataset_dir, "ocr_output.txt")
    marks_path = os.path.join(dataset_dir, "student_marks.json")
    
    # Load files
    with open(schema_path, "r") as f:
        schema = json.load(f)
    with open(ocr_path, "r") as f:
        ocr_text = f.read()
    with open(marks_path, "r") as f:
        marks_data = json.load(f)
        
    print("="*60)
    print("CA STAGE 4: Specialized Answer Alignment")
    print("="*60)
    
    # 1. Parse OCR text to pages
    print("Parsing OCR text...")
    student_pages = parse_ocr_to_pages(ocr_text)
    
    # 2. Extract manifest questions (all keys in marks_data['marks'])
    marks_dict = marks_data.get("marks", {})
    manifest_questions = []
    for k in marks_dict.keys():
        # Skip aggregate keys like C1, C2
        if not k.startswith('C'):
            manifest_questions.append(k)
                
    print(f"Manifest Questions (From JSON): {manifest_questions}")
    
    # 3. Align answers
    print("Aligning student answers using Claude with manifest enforcement...")
    aligned_schema = align_answers_to_schema_claude(student_pages, schema, manifest_questions=manifest_questions)
    
    # 4. Global Answer Propagation (to handle redundant nodes)
    print("Propagating answers across redundant schema nodes...")
    propagate_answers_in_schema(aligned_schema)
    
    # 5. Inject marks
    print("Injecting student marks into aligned schema...")
    inject_marks_into_schema(aligned_schema, marks_data)
    
    # 6. Validation: Ensure manifest questions are not empty
    print("Validating alignment against manifest...")
    def validate_manifest(node, manifest_keys, marks_dict):
        if isinstance(node, dict):
            qid = node.get("question_id")
            subp = node.get("subpart")
            if qid or subp:
                for k in manifest_keys:
                    if qid == k or subp == k or (qid and k in qid) or (subp and k in subp):
                        ms_entry = marks_dict.get(k, 0)
                        ms = ms_entry.get("scored", 0) if isinstance(ms_entry, dict) else ms_entry
                        if not node.get("student_answer") and ms > 0:
                            print(f"⚠️  CRITICAL: Question {k} (Marks Scored: {ms}) has an EMPTY student answer!")
            for v in node.values(): validate_manifest(v, manifest_keys, marks_dict)
        elif isinstance(node, list):
            for i in node: validate_manifest(i, manifest_keys, marks_dict)

    validate_manifest(aligned_schema, manifest_questions, marks_data.get("marks", {}))

    # 7. Save
    output_path = os.path.join(dataset_dir, "aligned_answers_with_marks.json")
    with open(output_path, "w") as f:
        json.dump(aligned_schema, f, indent=2, ensure_ascii=False)
        
    print(f"✓ Aligned answers with marks saved to: {output_path}")
    print("\nDone. Next: run_ca_feedback_5.py")

if __name__ == "__main__":
    main()
