import sys, os, json
sys.path.insert(0, '/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend')
from claude_grading.answer_aligner_claude import align_answers_to_schema_claude

with open('/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results/dataset_15166_final/schema_with_answers.json') as f:
    schema = json.load(f)

with open('/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results/dataset_15166_claude/ocr_output.txt') as f:
    ocr_text = f.read()

pages = []
blocks = ocr_text.split("=== Page ")
for block in blocks:
    if not block.strip(): continue
    try:
        header, content = block.split("===", 1)
        pages.append({"page": int(header.strip()), "text": content.strip()})
    except: pass

print(f"Parsed {len(pages)} pages")
# Only running the first part to see what Pass 1 & 2 produce
# Let's modify the aligner to dump intermediate JSONs
