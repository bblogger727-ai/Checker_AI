
import os
import sys
import json
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

from app.core.openai_client import client
from app.services.answer_aligner import align_answers_to_schema

# Mock Data for Q1 (Pages 10-11)
mock_pages = [
    {
        "page": 10,
        "text": """(ii) Computation of tax liability
    for Puja Ltd

|                      | CGST  | SGST  | IGST  |
|----------------------|-------|-------|-------|
| Outward Supply       |       |       |       |
| 1)                   |       |       |       |
| 2) Printing letter cards |       |       |       |
| Material - 8,00,000 @ 6% | 48,000 | 48,000 |       |
| Binding - 72,000 @ 9% | 6,480 | 6,480 |       |
| 3) Raw cotton        | 12,500 | 12,500 |       |
| 5,00,000 x 2.5%      |       |       |       |
| No ITC               |       |       |       |"""
    },
    {
        "page": 11,
        "text": """1. Maintenance  
    Service  
    32000 - goods - 6J  
    (GST subst  
    goods - 9J.  

    |        | 1920 | 1920 |
    |--------|------|------|
    |        | 7910 | 7920 |

    2. Car given on  
    hire to  
    state corp.  

    |        |      |      |
    |--------|------|------|
    |        | 76820| 76820|"""
    }
]

# Partial Schema for Q1
mock_schema = {
  "SectionB": {
    "Q1": {
      "question_id": "B-Q1",
      "question_number": "Q1",
      "question": "Poorva Impex Ltd... (ii) Printed letter cards... (iii) Supplied raw cotton... (iv) Supplied maintenance services... (v) Given on hire 10 cars...",
      "marks": 14,
      "student_answer": "" 
    }
  }
}

print("Running alignment on Q1 pages...")
result = align_answers_to_schema(mock_pages, mock_schema)
print(json.dumps(result, indent=2))
