import json
import os

base_dir = "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results/dataset_15925"

def patch_file(filename):
    path = os.path.join(base_dir, filename)
    if not os.path.exists(path): return
    
    with open(path, 'r') as f:
        data = json.load(f)
        
    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "Q1a" and isinstance(v, dict) and "answer_pages" in v:
                    # Q1a is actually on page 17
                    v["answer_pages"] = [17]
                    print(f"Patched Q1a in {filename} to {v['answer_pages']}")
                elif k == "Q5a" and isinstance(v, dict) and "answer_pages" in v:
                    # Q5a is actually on page 15
                    v["answer_pages"] = [15, 16]
                    print(f"Patched Q5a in {filename} to {v['answer_pages']}")
                else:
                    walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

patch_file("aligned_answers.json")
patch_file("grading_final.json")
