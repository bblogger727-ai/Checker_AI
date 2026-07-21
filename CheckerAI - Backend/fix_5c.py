import os
import sys
import json

sys.path.insert(0, "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend")
from dotenv import load_dotenv
load_dotenv()
from claude_grading.ca_feedback_generator import generate_ca_feedback

fb_file = "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results/dataset_FR_Manual_Run/feedback_final.json"
schema_file = "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results/dataset_FR_Manual_Run/schema_with_answers.json"

with open(fb_file, "r") as f:
    fb = json.load(f)

q5c_node = fb["SectionB"]["Q5"]["Q5c"]
q5c_node["marks"] = 5
q5c_node["marks_scored"] = 1

print("Regenerating feedback for Q5c with marks: 1/5")
new_fback = generate_ca_feedback(
    q5c_node["question_text"], 
    q5c_node["model_answer"], 
    q5c_node["student_answer"], 
    5, 
    1
)

q5c_node["feedback"] = new_fback

with open(fb_file, "w") as f:
    json.dump(fb, f, indent=2)

with open(schema_file, "r") as f:
    schema = json.load(f)

if "SectionB" in schema and "Q5" in schema["SectionB"] and "Q5c" in schema["SectionB"]["Q5"]:
    schema["SectionB"]["Q5"]["Q5c"]["marks"] = 5
    schema["SectionB"]["Q5"]["Q5c"]["marks_scored"] = 1
    with open(schema_file, "w") as f:
        json.dump(schema, f, indent=2)

print("Saved updated feedback and schema. Ready for report generation.")
