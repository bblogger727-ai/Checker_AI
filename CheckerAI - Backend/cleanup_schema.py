import json
import re
import os

def normalize_subpart(s):
    if not s: return ""
    # Extract numbers like 1.6 from strings
    match = re.search(r'(\d+\.\d+)', str(s))
    if match: return match.group(1)
    return str(s).lower().strip()

def cleanup_schema(input_path, output_path):
    if not os.path.exists(input_path):
        print(f"Error: {input_path} not found.")
        return
        
    with open(input_path, 'r') as f:
        data = json.load(f)
    
    questions = {} # logical_id -> data
    
    def _visit(node):
        if isinstance(node, dict):
            # Check if this looks like a question node
            has_q = "question_text" in node or "question" in node
            has_ans = "model_answer" in node
            has_id = "subpart" in node or "question_id" in node
            
            if has_q or has_ans or has_id:
                subp = node.get("subpart")
                qid = node.get("question_id")
                qnum = node.get("question_number")
                
                # Determine logical ID (e.g. 1.6)
                logical_id = normalize_subpart(subp) or normalize_subpart(qid) or normalize_subpart(qnum)
                if logical_id:
                    # Filter for only .6, .7, .8 as requested by user
                    if not any(logical_id.endswith(suffix) for suffix in [".6", ".7", ".8"]):
                        return

                    if logical_id not in questions:
                        questions[logical_id] = {
                            "question_id": f"Q{logical_id}",
                            "question_number": logical_id.split('.')[0] if '.' in logical_id else logical_id,
                            "subpart": logical_id,
                            "question_text": "",
                            "model_answer": "",
                            "marks": None
                        }
                    
                    q = questions[logical_id]
                    
                    # Merge question text
                    txt = node.get("question_text") or node.get("question", "")
                    if txt and "not provided" not in txt.lower() and len(txt) > len(q["question_text"]):
                        q["question_text"] = txt
                    
                    # Merge model answer
                    ans = node.get("model_answer", "")
                    if ans and "not provided" not in ans.lower() and len(ans) > len(q["model_answer"]):
                        q["model_answer"] = ans
                    
                    # Merge marks
                    m = node.get("marks")
                    if isinstance(m, (int, float)):
                        q["marks"] = m
                    elif isinstance(m, str) and m.replace('.','',1).isdigit():
                        q["marks"] = float(m)
            
            for v in node.values(): _visit(v)
        elif isinstance(node, list):
            for item in node: _visit(item)

    _visit(data)
    
    # Final structure: flat list organized by Case Study
    refined = {"CaseStudies": {}}
    for lid, q in questions.items():
        cs_num = lid.split('.')[0]
        cs_key = f"CaseStudy{cs_num}"
        if cs_key not in refined["CaseStudies"]:
            refined["CaseStudies"][cs_key] = {"questions": []}
        refined["CaseStudies"][cs_key]["questions"].append(q)
    
    # Sort
    for cs in refined["CaseStudies"].values():
        cs["questions"].sort(key=lambda x: x["subpart"])
        
    with open(output_path, 'w') as f:
        json.dump(refined, f, indent=2, ensure_ascii=False)
    print(f"✓ Cleaned schema saved to: {output_path}")

if __name__ == "__main__":
    dataset_id = "DMCI_TEST"
    base = "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results"
    inp = f"{base}/dataset_{dataset_id}/schema_with_answers.json"
    out = f"{base}/dataset_{dataset_id}/schema_with_answers_fixed.json"
    cleanup_schema(inp, out)
    # Overwrite the original for the next stages
    import shutil
    shutil.copy(out, inp)
    print(f"✓ Overwrote original schema with cleaned version.")
