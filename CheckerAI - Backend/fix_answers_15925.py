import json
import re

path = "grading_results/dataset_15925/aligned_answers.json"
with open(path, 'r') as f:
    data = json.load(f)

q1a_raw = data["SectionB"]["Q1"]["Q1a"]["student_answer"]

parts = re.split(r"(Q\.\s*5\)\s*a\))", q1a_raw)
parts2 = re.split(r"(Q\.1\)\s*a\))", parts[2])

q5a_text = parts[1] + parts2[0]
q1a_text = parts2[1] + parts2[2]

print("--- NEW Q5a ---")
print(q5a_text.strip())
print("--- NEW Q1a ---")
print(q1a_text.strip())

data["SectionB"]["Q1"]["Q1a"]["student_answer"] = q1a_text.strip()
data["SectionB"]["Q1"]["Q1a"]["answer_pages"] = [17]

data["SectionB"]["Q5"]["Q5a"]["student_answer"] = q5a_text.strip()
data["SectionB"]["Q5"]["Q5a"]["answer_pages"] = [15, 16]

with open(path, 'w') as f:
    json.dump(data, f, indent=2)

