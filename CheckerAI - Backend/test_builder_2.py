import sys, os, json
sys.path.insert(0, '/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend')
from claude_grading.model_answer_builder_claude import extract_pdf_text_tesseract, build_model_answers_claude

print('Loading cached schema from dataset_15166_claude...')
with open('/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results/dataset_15166_claude/schema_with_answers.json') as f:
    schema = json.load(f)

def clean_schema(node):
    if not isinstance(node, dict): return
    if 'model_answer' in node:
        node['model_answer'] = ''
    for k, v in node.items():
        if isinstance(v, dict):
            clean_schema(v)
            
clean_schema(schema)

sa_path = '/Users/gaureshmantri/Desktop/CheckerAI/15166sa.pdf'

print('Extracting text from SA...')
with open('/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/pipeline_temp/2_sa_text.txt') as f:
    sa_text = f.read()

print('Building model answers with Claude + Vision...')
schema_with_answers = build_model_answers_claude(schema, sa_text, sa_path)

output_path = '/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results/dataset_15166_claude_v3/schema_with_answers.json'
os.makedirs(os.path.dirname(output_path), exist_ok=True)
with open(output_path, 'w') as f:
    json.dump(schema_with_answers, f, indent=2, ensure_ascii=False)

print(f'\nSuccess! Saved to {output_path}')

for k, v in schema_with_answers.get('SectionA', {}).items():
    if isinstance(v, dict):
        ma = v.get('model_answer', '')
        print(f'{k}: {len(ma)} chars')
