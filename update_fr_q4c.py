import json

src_path = "/Users/gaureshmantri/Documents/Secure PDF Extraction/All_Paper_JSONs/Final/FR_Mock_Paper_1.json"
dest_path = "/Users/gaureshmantri/Desktop/CheckerAI/All_Paper_JSONs/Final/FR_Mock_Paper_1.json"

with open(src_path, "r", encoding="utf-8") as f:
    src_data = json.load(f)

with open(dest_path, "r", encoding="utf-8") as f:
    dest_data = json.load(f)

# Find Q4 in src and dest
q4_src = next(q for q in src_data.get("section_b", []) if q.get("q_main") == 4)
q4_dest = next(q for q in dest_data.get("section_b", []) if q.get("q_main") == 4)

sq4c_src = next(sq for sq in q4_src.get("sub_questions", []) if sq.get("label") == "c")

# Update Q4c in dest
for i, sq in enumerate(q4_dest.get("sub_questions", [])):
    if sq.get("label") == "c":
        print("Previous Q4c Question in DEST:\n", sq.get("question")[:200])
        print("Previous Q4c Answer in DEST:\n", sq.get("answer")[:200])
        
        sq["question"] = sq4c_src["question"]
        sq["answer"] = sq4c_src["answer"]
        if "chapter_number" in sq4c_src:
            sq["chapter_number"] = sq4c_src["chapter_number"]
        if "chapter_name" in sq4c_src:
            sq["chapter_name"] = sq4c_src["chapter_name"]
        if "unique_id" in sq4c_src:
            sq["unique_id"] = sq4c_src["unique_id"]
            
        print("\n--- Updated ---")
        print("New Q4c Question in DEST:\n", sq["question"])
        print("New Q4c Answer in DEST:\n", sq["answer"])
        break

with open(dest_path, "w", encoding="utf-8") as f:
    json.dump(dest_data, f, indent=2, ensure_ascii=False)

print("\nSuccessfully updated Q4c in", dest_path)
