import json

src_path = "/Users/gaureshmantri/Documents/Secure PDF Extraction/All_Paper_JSONs/Inter/LAW_Mock_Paper_1.json"
dest_path = "/Users/gaureshmantri/Desktop/CheckerAI/All_Paper_JSONs/Inter/LAW_Mock_Paper_1.json"

with open(src_path, "r", encoding="utf-8") as f:
    src_data = json.load(f)

with open(dest_path, "r", encoding="utf-8") as f:
    dest_data = json.load(f)

# 1. Update Q1a
q1_src = next(q for q in src_data.get("section_b", []) if q.get("q_main") == 1)
q1_dest = next(q for q in dest_data.get("section_b", []) if q.get("q_main") == 1)
sq1a_src = next(sq for sq in q1_src.get("sub_questions", []) if sq.get("label") == "a")

for sq in q1_dest.get("sub_questions", []):
    if sq.get("label") == "a":
        print("--- Updating Q1a ---")
        sq["question"] = sq1a_src["question"]
        sq["answer"] = sq1a_src["answer"]
        if "chapter_number" in sq1a_src:
            sq["chapter_number"] = sq1a_src["chapter_number"]
        if "chapter_name" in sq1a_src:
            sq["chapter_name"] = sq1a_src["chapter_name"]
        if "unique_id" in sq1a_src:
            sq["unique_id"] = sq1a_src["unique_id"]
        print("Updated Q1a successfully.")
        break

# 2. Update Q6c
q6_src = next(q for q in src_data.get("section_b", []) if q.get("q_main") == 6)
q6_dest = next(q for q in dest_data.get("section_b", []) if q.get("q_main") == 6)
sq6c_src = next(sq for sq in q6_src.get("sub_questions", []) if sq.get("label") == "c")

for sq in q6_dest.get("sub_questions", []):
    if sq.get("label") == "c":
        print("--- Updating Q6c ---")
        sq["question"] = sq6c_src["question"]
        sq["answer"] = sq6c_src["answer"]
        if "chapter_number" in sq6c_src:
            sq["chapter_number"] = sq6c_src["chapter_number"]
        if "chapter_name" in sq6c_src:
            sq["chapter_name"] = sq6c_src["chapter_name"]
        if "unique_id" in sq6c_src:
            sq["unique_id"] = sq6c_src["unique_id"]
        print("Updated Q6c successfully.")
        break

with open(dest_path, "w", encoding="utf-8") as f:
    json.dump(dest_data, f, indent=2, ensure_ascii=False)

print("\nSuccessfully updated LAW_Mock_Paper_1.json")
