import sys, os, json
sys.path.insert(0, '/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend')
from claude_grading.model_answer_builder_claude import split_into_semantic_chunks, claude_client, CLAUDE_MODEL

with open('/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/pipeline_temp/2_sa_text.txt') as f:
    text = f.read()

chunks = [(l, t) for l, t in split_into_semantic_chunks(text) if l != 'MCQ_QUESTIONS']
chunk_label, chunk_text = chunks[1]

with open('/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/pipeline_output/schema.json') as f:
    schema = json.load(f)

prompt = f"""You are an expert CA examiner.
You are given chunk 2/3 of the solution text (label: 'pages_5_to_8').

Your task:
1. Review the provided Question Schema.
2. Search THIS CHUNK of text for answers to ANY of those questions.
3. If an answer is found, extract it into the `model_answer` field.

**NON-NEGOTIABLE RULES:**
1. **EXTRACT EVERYTHING**: The `model_answer` MUST contain the **entirety** of the solution text for that question.
   - Include ALL introductory lines.
   - Include ALL tables, calculations, and working notes.
   - Include ALL reasoning and legal provisions.
   - **DO NOT SUMMARIZE**. Do not truncate.
   - Every word in the solution text (except the question itself) MUST be assigned to a model answer.

2. **MCQ HANDLING**: 
   - Look for a specialized table/box at the **END OF THE SECTION** (e.g. "MCQ No. Most Appropriate Answer").
   - Construct the answer by combining the Option + Text.
   - **CRITICAL**: If the solution text provides reasoning for the MCQ (not just the table), INCLUDE THE REASONING.

3. **FORMATTING**:
   - Preserve markdown tables.
   - Preserve lists and bullet points.
   - Preserve all numerical calculations exactly as written.

4. **EMPTY ANSWERS**:
   - If an answer is NOT found in this chunk, leave `model_answer` as null (or "").
   - Do NOT hallucinate answers.

---
Question Schema (Look for these IDs):
{json.dumps(schema, indent=2)}

---
Chunk Text:
{chunk_text}

IMPORTANT: Respond with ONLY the JSON object — the same schema structure with model_answer fields populated. No explanation, no prose — just the raw JSON."""

response = claude_client.messages.create(
    model=CLAUDE_MODEL,
    max_tokens=8192,
    system="You are a strict JSON extraction assistant. Return the same schema structure with model_answer fields populated. Output ONLY valid JSON.",
    messages=[{"role": "user", "content": prompt}],
    temperature=0
)

print('--- RAW CLAUDE RESPONSE ---')
print(response.content[0].text[:1000])
print('... (truncated) ...')
print(response.content[0].text[-1000:])
print('--- STOP REASON ---')
print(response.stop_reason)
