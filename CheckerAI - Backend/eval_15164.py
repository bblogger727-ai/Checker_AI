import sys, os, json
sys.path.insert(0, '/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend')
from claude_grading.answer_aligner_claude import align_answers_to_schema_claude
from claude_grading.answer_grader_claude import grade_all_answers

print("=== EVALUATION FOR PAPER 15164 ===")

# 1. Load schema
schema_path = '/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results/dataset_15164/schema_with_answers.json'
with open(schema_path) as f:
    schema = json.load(f)

# 2. Load OCR
ocr_path = '/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results/dataset_15164/ocr_output.txt'
with open(ocr_path) as f:
    ocr_text = f.read()

pages = []
# Handle both "=== Page " and "=== PAGE " just in case
if "=== PAGE " in ocr_text:
    blocks = ocr_text.split("=== PAGE ")
else:
    blocks = ocr_text.split("=== Page ")

for block in blocks:
    if not block.strip(): continue
    try:
        # Split at the second triple-equals if it exists, or just take the first line as header
        lines = block.strip().split('\n', 1)
        header = lines[0].replace('===', '').strip()
        content = lines[1] if len(lines) > 1 else ""
        pages.append({"page": int(header), "text": content.strip()})
    except Exception as e:
        print(f"Skipping block due to error: {e}")

print(f"Loaded {len(pages)} student pages from {ocr_path}")

# 3. Align answers using Claude (FRESH PASS)
print("\n--- STAGE 4: Answer Alignment ---")
aligned = align_answers_to_schema_claude(pages, schema)

aligned_path = '/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results/dataset_15164/aligned_answers_claude.json'
with open(aligned_path, 'w') as f:
    json.dump(aligned, f, indent=2)

# 4. Grade answers using Claude
print("\n--- STAGE 5: Grading ---")
results = grade_all_answers(aligned, aligned)

grading_path = '/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results/dataset_15164/grading_final_claude.json'
with open(grading_path, 'w') as f:
    json.dump(results, f, indent=2)

# 5. Summary
graded = results.get('graded_answers', {})
total_score = 0
total_max = 0

print("\n========== FINAL PIPELINE RESULTS (15164) ==========")
for section_key, section in graded.items():
    for qk, qv in section.items():
        if isinstance(qv, dict):
            if 'marks_obtained' in qv:
                score = qv["marks_obtained"]
                max_score = qv["marks_total"]
                total_score += score
                total_max += max_score
                print(f'{qk}: {score}/{max_score} | Tier={qv.get("tier", "")}')
                print(f'   Feedback: {qv.get("feedback", "")[:200]}...')
            else:
                for sk, sv in qv.items():
                    if isinstance(sv, dict) and 'marks_obtained' in sv:
                        score = sv["marks_obtained"]
                        max_score = sv["marks_total"]
                        total_score += score
                        total_max += max_score
                        print(f'{qk}.{sk}: {score}/{max_score} | Tier={sv.get("tier", "")}')
                        print(f'   Feedback: {sv.get("feedback", "")[:200]}...')

print(f"\nFinal Total Score: {total_score} / {total_max}")
