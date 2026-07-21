import os
import json
import re
import anthropic
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
CLAUDE_MODEL = "claude-sonnet-4-6"

def parse_student_marks(last_page_text: str) -> dict:
    """
    Parse student marks from the last page text using Claude.
    Returns a dict mapping question_id (or number) to marks scored.
    """
    prompt = f"""
You are an expert data extractor. You are given the text extracted from the LAST PAGE of a CA student's answer sheet.
This page contains a summary table of the marks scored by the student and the total marks ALLOTTED for each question.

Your task:
1. Extract the Marks Scored AND the Marks Allotted (Max Marks) for each question.
2. For Case Studies (C1, C2, C3, C4, C5): These are aggregates. Capture them, but also ensure they reflect the sum of their respective subparts (.6, .7, .8).
3. Extract subparts: 1.6, 1.7, 1.8, 2.6, 2.7, 2.8, etc.

Example Input Text:
"C1: 9.5/15 (1.6: 1/5, 1.7: 3.5/5, 1.8: 5/5), C2: 0/15, Total: 32.5/60"

Example Output JSON:
{{
  "marks": {{
    "C1": {{ "scored": 9.5, "allotted": 15 }},
    "1.6": {{ "scored": 1, "allotted": 5 }},
    "1.7": {{ "scored": 3.5, "allotted": 5 }},
    "1.8": {{ "scored": 5, "allotted": 5 }},
    "C2": {{ "scored": 0, "allotted": 15 }},
    "2.6": {{ "scored": 0, "allotted": 5 }},
    "2.7": {{ "scored": 0, "allotted": 5 }},
    "2.8": {{ "scored": 0, "allotted": 5 }}
  }},
  "total_scored": 32.5,
  "total_allotted": 60
}}

---
LAST PAGE TEXT:
{last_page_text}
"""

    print(f"[CA Mark Parser] Parsing marks from last page text...", flush=True)
    
    try:
        response = claude_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system="You are a strict JSON extraction assistant. Output ONLY valid JSON. No prose.",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        
        text = response.content[0].text.strip()
        if text.startswith('```'):
            text = re.sub(r'^```json?\s*\n?', '', text)
            text = re.sub(r'\n?```\s*$', '', text)
            
        return json.loads(text)
        
    except Exception as e:
        print(f"[CA Mark Parser] Error: {e}", flush=True)
        return {"marks": {}}
