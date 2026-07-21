#!/usr/bin/env python3
"""Stage 1: Generate schema for FR 14865 paper using gpt-4o."""
import os, sys, json
import fitz  # PyMuPDF
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()
from app.core.openai_client import client

QP_PATH = "/Users/gaureshmantri/Desktop/CheckerAI/FR QP 14865 .pdf"

def extract_pdf_text(pdf_path: str) -> str:
    """Extract all text from PDF using PyMuPDF."""
    doc = fitz.open(pdf_path)
    text = ""
    for page_num, page in enumerate(doc, 1):
        text += f"\n\n=== Page {page_num} ===\n{page.get_text()}"
    return text

# Extract QP text
print("Extracting QP text...")
qp_text = extract_pdf_text(QP_PATH)
print(f"QP text: {len(qp_text)} chars")

# Save to pipeline_temp
os.makedirs("pipeline_temp", exist_ok=True)
with open("pipeline_temp/1_qp_text.txt", "w") as f:
    f.write(qp_text)
print("✓ QP text saved")

# Generate schema
prompt = """You are given the text of a CA exam question paper (Financial Reporting).

Extract the question structure. For each question/subquestion, extract:
- question (full question text)
- marks (integer)
- or_group (null or string for OR alternatives, e.g. "or_A_1")

Return JSON with this structure:
{
  "SectionA": {
    "Q1": { "question": "...", "marks": 5, "or_group": null },
    "Q2": {
      "a": { "question": "...", "marks": 5, "or_group": null },
      "b": { "question": "...", "marks": 5, "or_group": null }
    }
  }
}

OR question detection: If questions are marked as alternatives (e.g., "Q1 OR Q1A"), 
assign the SAME or_group ID like "or_A_1".

Rules:
- Extract ONLY the question statements, NOT answers
- Preserve original numbering
- Output ONLY valid JSON
- Marks must be integers

Question Paper:
""" + qp_text

print("Calling GPT-4o for schema generation...")
response = client.chat.completions.create(
    model='gpt-4o',
    messages=[
        {'role': 'system', 'content': 'You are a strict JSON generator for exam question schemas.'},
        {'role': 'user', 'content': prompt}
    ],
    response_format={"type": "json_object"},
    temperature=0
)

output = response.choices[0].message.content.strip()
schema = json.loads(output)

os.makedirs("../pipeline_output", exist_ok=True)
out_path = "/Users/gaureshmantri/Desktop/CheckerAI/pipeline_output/schema.json"
with open(out_path, "w") as f:
    json.dump(schema, f, indent=2, ensure_ascii=False)

print(f"✓ Schema saved to {out_path}")
print(f"Sections: {list(schema.keys())}")
for k in schema:
    if isinstance(schema[k], dict):
        print(f"  {k}: {list(schema[k].keys())}")
