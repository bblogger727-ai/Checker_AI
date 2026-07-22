
import json
import copy

def normalize_schema_structure(data: dict) -> dict:
    """
    Ensures the schema follows the standard nested structure:
    SectionA: { MCQ: { ... } }
    SectionB: { Q1: { ... }, Q2: { a: {}, b: {}, ... }, ... }
    
    Moves root-level SectionB questions (Q1, Q2, Q3, Q4) into SectionB if they are at the root.
    Consolidates DivisionA/SectionA etc.
    """
    if not isinstance(data, dict):
        return data
        
    result = copy.deepcopy(data)
    
    # 1. Ensure SectionA and SectionB exist
    if "SectionA" not in result:
        result["SectionA"] = {}
    if "SectionB" not in result:
        result["SectionB"] = {}
        
    # 2. Handle DivisionA / DivisionB synonyms
    if "DivisionA" in result:
        result["SectionA"].update(result["DivisionA"])
        del result["DivisionA"]
    if "DivisionB" in result:
        result["SectionB"].update(result["DivisionB"])
        del result["DivisionB"]
        
    # 3. Identify SectionB questions at root and move them
    # Common root keys that should be in SectionB
    section_b_keys = ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"]
    for k in list(result.keys()):
        if k in section_b_keys:
            # If Q1 is at root, move it to SectionB
            if k not in result["SectionB"] or (isinstance(result["SectionB"][k], dict) and not result["SectionB"][k].get("question_text")):
                 result["SectionB"][k] = result[k]
                 print(f"[Normalization] Moved root {k} to SectionB")
            else:
                 # Merge if necessary (preserve existing if more complete)
                 pass
            del result[k]

    # 4. Fix MCQ IDs and SectionA structure
    if "MCQ" in result["SectionA"]:
        mcqs = result["SectionA"]["MCQ"]
        new_mcqs = {}
        for k, v in mcqs.items():
            new_key = str(k)
            if new_key.startswith("Q") and new_key[1:].isdigit():
                new_key = new_key[1:]
            elif new_key.startswith("MCQ-") and new_key[4:].isdigit():
                new_key = new_key[4:]
            
            # Ensure question_id is consistent
            if isinstance(v, dict):
                if not v.get("question_id"):
                    v["question_id"] = f"A-MCQ-{new_key}"
                
            new_mcqs[new_key] = v
        result["SectionA"]["MCQ"] = new_mcqs
    
    # 5. Ensure question_id prefixes are correct in SectionB
    for q_key, q_val in result["SectionB"].items():
        if isinstance(q_val, dict):
            # If it's a top-level question like Q1
            if q_val.get("question_text") and not q_val.get("question_id"):
                q_val["question_id"] = f"B-{q_key}"
            
            # If it has subparts
            for sub_key, sub_val in q_val.items():
                if isinstance(sub_val, dict) and sub_val.get("question_text"):
                    if not sub_val.get("question_id"):
                        sub_val["question_id"] = f"B-{q_key}-{sub_key}"

    return result

def save_normalized_json(path: str):
    """Loads, normalizes, and saves a JSON file."""
    if not os.path.exists(path):
        return
    try:
        with open(path, "r") as f:
            data = json.load(f)
        normalized = normalize_schema_structure(data)
        with open(path, "w") as f:
            json.dump(normalized, f, indent=2)
        print(f"[Normalization] Successfully normalized {path}")
    except Exception as e:
        print(f"[Normalization] Error normalizing {path}: {e}")

import os
