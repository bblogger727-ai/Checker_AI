import json

with open("grading_results/dataset_15903/grading_final.json", "r") as f:
    data = json.load(f)

graded = data.get("graded_answers", {})
section_b = graded.get("SectionB", {})
if not section_b:
    section_b = graded.get("PART_I", {})

total_possible = 40.0
is_portionwise = True

def q_total_obtained(q_content):
    if "marks_obtained" in q_content:
        return float(q_content.get("marks_obtained", 0))
    total = 0.0
    for v in q_content.values():
        if isinstance(v, dict) and "marks_obtained" in v:
            total += float(v.get("marks_obtained", 0))
    return total

optional_scores = []
compulsory_q = "Q1"
for q_key, q_content in section_b.items():
    if q_key == compulsory_q:
        continue
    score = q_total_obtained(q_content)
    optional_scores.append((q_key, score))

counted_keys = set(section_b.keys())
total_obtained = 0.0
for q_key in counted_keys:
    total_obtained += q_total_obtained(section_b.get(q_key, {}))

percentage = round((total_obtained / total_possible) * 100, 2)
data["metadata"]["total_marks_possible"] = total_possible
data["metadata"]["total_marks_obtained"] = total_obtained
data["metadata"]["percentage"] = percentage

with open("grading_results/dataset_15903/grading_final.json", "w") as f:
    json.dump(data, f, indent=2)

print(f"Fixed total: {total_obtained}/{total_possible}")
