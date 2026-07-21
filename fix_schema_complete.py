import json
import re

def fix_schema(input_path, output_path):
    with open(input_path, "r", encoding="utf-8") as f:
        schema = json.load(f)

    print("--- Fixing Schema ---")

    # 1. Move "Kunal" (SectionB-Q1-a) to SectionA-Q1-a if it exists
    kunal_question = None
    if "SectionB" in schema and "Q1" in schema["SectionB"]:
        q1_group = schema["SectionB"]["Q1"]
        # It might be a dict "a", "null", etc.
        keys_to_remove = []
        for key, q_data in list(q1_group.items()):
            text = q_data.get("full_question_text", "")
            # Robust check
            if "Kunal" in text:
                print(f"Found Kunal Question in SectionB-Q1-{key}. Moving to SectionA-Q1.")
                kunal_question = q_data.copy() # Copy to be safe
                kunal_question["question_id"] = "SectionA-Q1-a"
                kunal_question["question_number"] = 1
                kunal_question["subpart"] = "a"
                keys_to_remove.append(key)
        
        # Remove Kunal from B
        for k in keys_to_remove:
            del schema["SectionB"]["Q1"][k]

    if kunal_question:
        if "SectionA" not in schema:
            schema["SectionA"] = {}
        if "Q1" not in schema["SectionA"]:
            schema["SectionA"]["Q1"] = {}
        schema["SectionA"]["Q1"]["a"] = kunal_question

    # 2. Fix valid SectionB-Q1 questions (Surya)
    if "SectionB" in schema and "Q1" in schema["SectionB"]:
        q1_group = schema["SectionB"]["Q1"]
        new_q1_group = {}
        
        for key, q_data in q1_group.items():
            text = q_data.get("full_question_text", "")
            if "Surya" in text:
                print(f"Found Surya Question in SectionB-Q1-{key}. Keeping in SectionB-Q1.")
                # Ensure we don't overwrite if 'a' exists (though Kunal should be gone)
                # If Kunal is gone, 'a' is free.
                # If 'a' is taken by something else, use 'b'?
                new_key = "a"
                if new_key in new_q1_group:
                    new_key = "b" # Fallback
                
                q_data["question_id"] = f"SectionB-Q1-{new_key}"
                q_data["subpart"] = new_key
                new_q1_group[new_key] = q_data
            else:
                new_key = key if key != "null" else "unknown"
                # Collision check
                while new_key in new_q1_group:
                    new_key += "_dup"
                new_q1_group[new_key] = q_data
        
        schema["SectionB"]["Q1"] = new_q1_group

    # 3. Normalize "null" keys generally
    for section_name, section in schema.items():
        if not isinstance(section, dict): continue
        for q_num, q_group in section.items():
            if not isinstance(q_group, dict): continue
            
            # If q_group has "null" key, rename it
            if "null" in q_group:
                print(f"Fixing 'null' key in {section_name}-{q_num}")
                content = q_group.pop("null")
                # Find a free letter
                existing_keys = q_group.keys()
                char_code = 97 # 'a'
                while chr(char_code) in existing_keys:
                    char_code += 1
                new_key = chr(char_code)
                q_group[new_key] = content
                # Update subpart/ID
                if content.get("subpart") is None:
                    content["subpart"] = new_key
                # Update ID if it looks like ...-null
                old_id = content.get("question_id", "")
                if old_id.endswith("null") or "null" in old_id:
                    # Construct ID: Section-QNum-Subpart
                    new_id = f"{section_name}-{q_num}-{new_key}"
                    content["question_id"] = new_id

    # 4. Save
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
    print(f"Fixed schema saved to {output_path}")

if __name__ == "__main__":
    fix_schema(
        "pipeline_output/schema_chunked.json",
        "pipeline_output/schema_final_fixed.json"
    )
