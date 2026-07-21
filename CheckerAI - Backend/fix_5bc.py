import os
import sys
import json
import anthropic

sys.path.insert(0, "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend")
from dotenv import load_dotenv
load_dotenv()

from app.services.answer_parser import parse_ocr_to_pages
from claude_grading.answer_aligner_claude import align_answers_to_schema_claude
from claude_grading.ca_feedback_generator import generate_ca_feedback

dataset_dir = "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results/dataset_FR_Manual_Run"

print("1. Reading model text to extract 5b and 5c...")
with open(os.path.join(dataset_dir, "model_text.txt"), "r") as f:
    model_text = f.read()

# Claude Extraction for precise 5b and 5c answers
client = anthropic.Anthropic()
prompt = f"""
Here is the text of a model answer paper:
<text>
{model_text}
</text>

Please extract the complete text of Question 5(b) and Question 5(c) along with their complete model answers.
Make sure to include calculations, tables, and notes.

Format your output EXACTLY as this JSON:
{{
  "5b": "complete model answer text inclusive of the question text if present",
  "5c": "complete model answer text inclusive of the question text if present"
}}
"""
print("Calling Claude for model answer extraction...")
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=4000,
    messages=[{"role": "user", "content": prompt}],
    temperature=0
)
res_text = response.content[0].text

try:
    start_idx = res_text.find("{")
    end_idx = res_text.rfind("}") + 1
    ans_json = json.loads(res_text[start_idx:end_idx])
except Exception as e:
    print(f"Failed to parse Claude output: {res_text}")
    sys.exit(1)

model_5b = ans_json.get("5b", "")
model_5c = ans_json.get("5c", "")

print("2. Building mini-schema...")
mini_schema = {
  "SectionB": {
    "Q5": {
      "5b": {
        "question_id": "SectionB-Q5b",
        "question_number": "Q5",
        "subpart": "b",
        "question_text": "Question 5(b)",
        "marks": 5,
        "marks_scored": 5,
        "model_answer": model_5b,
        "student_answer": "",
        "answer_pages": []
      },
      "5c": {
        "question_id": "SectionB-Q5c",
        "question_number": "Q5",
        "subpart": "c",
        "question_text": "Question 5(c)",
        "marks": 1,
        "marks_scored": 1,
        "model_answer": model_5c,
        "student_answer": "",
        "answer_pages": []
      }
    }
  }
}

print("3. Reading OCR text...")
with open(os.path.join(dataset_dir, "ocr_output.txt"), "r") as f:
    ocr_text = f.read()

student_pages = parse_ocr_to_pages(ocr_text)

print("4. Aligning student answers for 5b and 5c...")
manifest = ["SectionB-Q5b", "SectionB-Q5c"]
aligned_schema = align_answers_to_schema_claude(student_pages, mini_schema, manifest_questions=manifest)

q5b_node = aligned_schema["SectionB"]["Q5"]["5b"]
q5c_node = aligned_schema["SectionB"]["Q5"]["5c"]

print("5. Grading and generating feedback...")
fback_5b = generate_ca_feedback(q5b_node["question_text"], q5b_node["model_answer"], q5b_node.get("student_answer", ""), q5b_node["marks"], q5b_node["marks_scored"])
fback_5c = generate_ca_feedback(q5c_node["question_text"], q5c_node["model_answer"], q5c_node.get("student_answer", ""), q5c_node["marks"], q5c_node["marks_scored"])

def make_fback_item(node, fb):
    return {
      "question_id": node["question_id"],
      "question_number": node["question_number"],
      "subpart": node["subpart"],
      "question_text": node["question_text"],
      "marks": node["marks"],
      "marks_scored": node["marks_scored"],
      "model_answer": node["model_answer"],
      "student_answer": node.get("student_answer", ""),
      "answer_pages": node.get("answer_pages", []),
      "feedback": fb
    }

fb_items = [make_fback_item(q5b_node, fback_5b), make_fback_item(q5c_node, fback_5c)]

print("6. Merging with existing feedback_final.json...")
fb_file = os.path.join(dataset_dir, "feedback_final.json")
if os.path.exists(fb_file):
    with open(fb_file, "r") as f:
        existing_fb = json.load(f)
else:
    existing_fb = {} # Initialize as dict if file doesn't exist

# Merge items into the hierarchical schema
if "SectionB" not in existing_fb:
    existing_fb["SectionB"] = {}
if "Q5" not in existing_fb["SectionB"]:
    existing_fb["SectionB"]["Q5"] = {}

existing_fb["SectionB"]["Q5"]["Q5b"] = fb_items[0]
existing_fb["SectionB"]["Q5"]["Q5c"] = fb_items[1]

with open(fb_file, "w") as f:
    json.dump(existing_fb, f, indent=2)

print("Targeted run for 5b and 5c complete!")
