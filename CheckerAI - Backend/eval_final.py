import sys, os, json
sys.path.insert(0, '/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend')
from claude_grading.answer_aligner_claude import align_answers_to_schema_claude
from claude_grading.answer_grader_claude import grade_all_answers

print("=== FINAL EVALUATION ===")

# 1. Load schema with Claude Answers we generated earlier (which include Vision Q3)
schema_path = '/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results/dataset_15166_final/schema_with_answers.json'
with open(schema_path) as f:
    schema = json.load(f)

# 2. Load the VALID, full 9-page OCR extracted from OpenAI
ocr_path = '/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results/dataset_15166/ocr_output.txt'
with open(ocr_path) as f:
    ocr_text = f.read()

pages = []
blocks = ocr_text.split("=== Page ")
for block in blocks:
    if not block.strip(): continue
    try:
        header, content = block.split("===", 1)
        pages.append({"page": int(header.strip()), "text": content.strip()})
    except: pass

print(f"Loaded {len(pages)} student pages from {ocr_path}")

# 3. Align answers using Claude
print("\n--- STAGE 4: Answer Alignment ---")
aligned = align_answers_to_schema_claude(pages, schema)

aligned_path = '/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results/dataset_15166_final/aligned_answers.json'
with open(aligned_path, 'w') as f:
    json.dump(aligned, f, indent=2)

# 4. Grade answers using Claude
print("\n--- STAGE 5: Grading ---")
results = grade_all_answers(aligned, aligned)

grading_path = '/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results/dataset_15166_final/grading_final.json'
with open(grading_path, 'w') as f:
    json.dump(results, f, indent=2)

# 5. Diff Grades vs Output
expected = {'Q1': 1.5, 'Q2': 0, 'Q3': 8, 'Q4': 3.5, 'Q5': 3, 'Q6': 0, 'Q7': 5}
graded = results.get('graded_answers', {})
total_score = 0
total_max = 0

print("\n========== FINAL PIPELINE RESULTS ==========")
for section_key, section in graded.items():
    for qk, qv in section.items():
        if isinstance(qv, dict):
            if 'marks_obtained' in qv:
                exp = expected.get(qk, '?')
                score = qv["marks_obtained"]
                max_score = qv["marks_total"]
                total_score += score
                total_max += max_score
                
                diff = score - exp if isinstance(exp, (int, float)) else '?'
                status = '✓' if diff != '?' and abs(diff) <= 0.5 else ('▲ OVER' if diff != '?' and diff > 0 else '▼ UNDER')
                print(f'{qk}: {score}/{max_score} | Expected={exp} | {status} | Tier={qv.get("tier", "")}')
                if status != '✓':
                    print(f'   Reason: {qv.get("feedback", "")[:150]}...')
            else:
                for sk, sv in qv.items():
                    if isinstance(sv, dict) and 'marks_obtained' in sv:
                        exp = expected.get(sk, '?')
                        score = sv["marks_obtained"]
                        max_score = sv["marks_total"]
                        total_score += score
                        total_max += max_score
                        
                        diff = score - exp if isinstance(exp, (int, float)) else '?'
                        status = '✓' if diff != '?' and abs(diff) <= 0.5 else ('▲ OVER' if diff != '?' and diff > 0 else '▼ UNDER')
                        print(f'{qk}.{sk}: {score}/{max_score} | Expected={exp} | {status} | Tier={sv.get("tier", "")}')
                        if status != '✓':
                            print(f'   Reason: {sv.get("feedback", "")[:150]}...')

print(f"\nFinal Total Score: {total_score} / {total_max}")
