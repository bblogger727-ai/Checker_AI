import json
import os

def repair_schema():
    # Path to the schema generated in the last run
    schema_path = "/Users/gaureshmantri/Desktop/CheckerAI/pipeline_output/schema_verified.json"
    
    if not os.path.exists(schema_path):
        print(f"Error: Schema file not found at {schema_path}")
        return

    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)

    # 1. Move SectionB-Q1 to SectionA-Q1 if it looks like the Salary question
    if "SectionB" in schema and "Q1" in schema["SectionB"]:
        q1_content = schema["SectionB"]["Q1"]
        # check content briefly (optional, but safe)
        if "a" in q1_content and "Mr. Kunal" in str(q1_content["a"]):
            print("Detected 'Mr. Kunal' (Salary Question) in SectionB-Q1. Moving to SectionA-Q1...")
            
            # Ensure SectionA exists
            if "SectionA" not in schema:
                schema["SectionA"] = {}
            
            # Move it
            schema["SectionA"]["Q1"] = q1_content
            
            # Remove from SectionB
            del schema["SectionB"]["Q1"]
            
            # Update question_ids to reflect new section
            if "a" in schema["SectionA"]["Q1"]:
                schema["SectionA"]["Q1"]["a"]["question_id"] = "SectionA-Q1-a"

    # Save repaired schema
    repaired_path = "/Users/gaureshmantri/Desktop/CheckerAI/pipeline_output/schema_repaired.json"
    with open(repaired_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
    
    print(f"Repaired schema saved to {repaired_path}")
    
    # Print summary
    print("Sections:", list(schema.keys()))
    for s in schema:
        print(f"  {s}:", list(schema[s].keys()))

if __name__ == "__main__":
    repair_schema()
