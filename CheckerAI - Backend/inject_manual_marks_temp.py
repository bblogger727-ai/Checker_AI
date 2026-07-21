import json
import os
import shutil

dataset_id = "FR_Manual_Run"
base = f"/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results/dataset_{dataset_id}"
schema_path = f"{base}/schema_with_answers.json"
output_path = f"{base}/schema_with_marks_enriched.json"

manual_marks = {
    "SectionB-Q1": 3.5, "SectionB-Q1a": 3.5, "SectionB-Q1b": 3.5, "SectionB-Q1c": 3.5, "SectionB-Q1c-Either": 3.5, "SectionB-Q1c-Or": 3.5,
    "SectionB-Q2a": 1,
    "SectionB-Q2b": 3.5,
    "SectionB-Q4a": 2.5,
    "SectionB-Q4b": 3.5,
    "SectionB-Q5a": 2,
    "SectionB-Q5b": 5, "SectionB-Q5c": 1,
    "SectionB-Q6a": 3.5, "SectionB-Q6b": 1, "SectionB-Q6c": 2.5
}

def enrich(node):
    if isinstance(node, dict):
        qid = str(node.get("question_id", ""))
        if qid in manual_marks:
            node["marks_scored"] = manual_marks[qid]
            print(f"Injected marks for {qid}: {manual_marks[qid]} / {node.get('marks')}")
                
        for v in node.values():
            enrich(v)
    elif isinstance(node, list):
        for i in node:
            enrich(i)

if not os.path.exists(schema_path):
    print(f"Error: {schema_path} does not exist.")
    exit(1)

with open(schema_path, 'r') as f:
    schema = json.load(f)

enrich(schema)

with open(output_path, 'w') as f:
    json.dump(schema, f, indent=2, ensure_ascii=False)

shutil.copy(output_path, schema_path)
print("Finished manual marks injection.")
