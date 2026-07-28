import json
import os
import glob
import copy

old_dir = "/Users/gaureshmantri/Desktop/CheckerAI/Inter" # Now contains Old papers
new_dir = "/Users/gaureshmantri/Desktop/CheckerAI/All_Paper_JSONs/Inter" # Now contains New papers

files_to_check = sorted(glob.glob(os.path.join(new_dir, "*.json")))

diff_count = 0
for new_path in files_to_check:
    fname = os.path.basename(new_path)
    old_path = os.path.join(old_dir, fname)
    if not os.path.exists(old_path):
        continue
        
    with open(old_path, "r", encoding="utf-8") as f:
        old_data = json.load(f)
    with open(new_path, "r", encoding="utf-8") as f:
        new_data = json.load(f)
        
    changed = False
    
    # --- Check Section A (MCQs) ---
    old_mcqs = {str(q.get("_serial") or q.get("q_num")): q for cs in old_data.get("section_a", []) for q in cs.get("questions", [])}
    
    for cs_idx, case_study in enumerate(new_data.get("section_a", [])):
        new_questions = []
        for q in case_study.get("questions", []):
            serial = str(q.get("_serial") or q.get("q_num"))
            if serial in old_mcqs:
                old_q = old_mcqs[serial]
                if q.get("question") != old_q.get("question"):
                    # Differs! Add OR group.
                    or_group_name = f"MCQ_{serial}_v1_v2"
                    
                    # Modify v1
                    q["or_group"] = or_group_name
                    q["question_id"] = f"A-MCQ-{serial}_v1"
                    
                    # Create v2
                    q_v2 = copy.deepcopy(old_q)
                    q_v2["_serial"] = f"{serial}_v2"
                    q_v2["q_num"] = f"{serial}_v2"
                    q_v2["or_group"] = or_group_name
                    q_v2["question_id"] = f"A-MCQ-{serial}_v2"
                    
                    new_questions.append(q)
                    new_questions.append(q_v2)
                    changed = True
                    print(f"[{fname}] Section A: Merged MCQ {serial} (v1/v2)")
                else:
                    new_questions.append(q)
            else:
                new_questions.append(q)
        case_study["questions"] = new_questions

    # --- Check Section B (Descriptive) ---
    old_sb = {str(q["q_main"]): q for q in old_data.get("section_b", [])}
    
    for main_q in new_data.get("section_b", []):
        q_main = str(main_q.get("q_main"))
        if q_main in old_sb:
            old_main = old_sb[q_main]
            old_subs = {s["label"]: s for s in old_main.get("sub_questions", [])}
            
            new_sub_qs = []
            for sub in main_q.get("sub_questions", []):
                lbl = sub["label"]
                if lbl in old_subs:
                    old_sub = old_subs[lbl]
                    if sub.get("question", "").strip() != old_sub.get("question", "").strip():
                        or_group_name = f"Q{q_main}{lbl}_v1_v2"
                        
                        # Modify v1
                        sub["label"] = f"{lbl}_v1"
                        sub["or_group"] = or_group_name
                        sub["question_id"] = f"B-Q{q_main}-Q{q_main}{lbl}_v1"
                        sub["question"] = f"[New Version - v1] " + sub.get("question", "")
                        
                        # Create v2
                        sub_v2 = copy.deepcopy(old_sub)
                        sub_v2["label"] = f"{lbl}_v2"
                        sub_v2["or_group"] = or_group_name
                        sub_v2["question_id"] = f"B-Q{q_main}-Q{q_main}{lbl}_v2"
                        sub_v2["question"] = f"[Old Version - v2] " + sub_v2.get("question", "")
                        
                        new_sub_qs.append(sub)
                        new_sub_qs.append(sub_v2)
                        changed = True
                        print(f"[{fname}] Section B: Merged Q{q_main}({lbl}) (v1/v2)")
                    else:
                        new_sub_qs.append(sub)
                else:
                    new_sub_qs.append(sub)
                    
            main_q["sub_questions"] = new_sub_qs
            
    if changed:
        with open(new_path, "w", encoding="utf-8") as f:
            json.dump(new_data, f, indent=2, ensure_ascii=False)
        diff_count += 1

print(f"\nSuccessfully merged v1/v2 differences into {diff_count} files in {new_dir}")
