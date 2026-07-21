#!/usr/bin/env python3
import os
import sys
import json
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

load_dotenv()

from app.services.solution_schema_builder import build_solution_schema

def main():
    text_path = os.path.join(BASE_DIR, "pipeline_temp/1_qp_text.txt")
    print(f"Loading QP text from {text_path}...")
    with open(text_path, "r") as f:
        text = f.read()
        
    print("Generating schema...", flush=True)
    schema = build_solution_schema(text)
    
    out_path = os.path.join(BASE_DIR, "pipeline_temp/test_schema.json")
    with open(out_path, "w") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
        
    print(f"Saved to {out_path}")
    
    # Print a quick summary of Q3 and Q4 marks
    print("\n--- Summary ---")
    for section, qs in schema.items():
        if not isinstance(qs, dict): continue
        for q_id, q_data in qs.items():
            if q_id in ["Q3", "Q4"]:
                print(f"{section} - {q_id}:")
                if "a" in q_data:
                    print(f"  (a) marks: {q_data['a'].get('marks')}")
                if "b" in q_data:
                    print(f"  (b) marks: {q_data['b'].get('marks')}")

if __name__ == "__main__":
    main()
