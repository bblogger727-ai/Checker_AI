"""
Update IDT_Mock_Paper_3.json in All_Paper_JSONs/Final/:
- Q4b: text has changed → update directly (replace with new src version)
- Q4c: question has changed → add as v1/v2 (old=v1 main, new=v2 as or_question)
"""
import json, copy, shutil

DEST_PAPER = "/Users/gaureshmantri/Desktop/CheckerAI/All_Paper_JSONs/Final/IDT_Mock_Paper_3.json"
SRC_PAPER  = "/Users/gaureshmantri/Documents/Secure PDF Extraction/All_Paper_JSONs/Final/IDT_Mock_Paper_3.json"

with open(DEST_PAPER) as f: d_dest = json.load(f)
with open(SRC_PAPER)  as f: d_src  = json.load(f)

def get_sub(data, q_main, label):
    for q in data.get("section_b", []):
        if q.get("q_main") == q_main:
            for sq in q.get("sub_questions", []):
                if sq.get("label") == label:
                    return copy.deepcopy(sq)
    return None

# --- Q4b: update text directly from src ---
src_q4b  = get_sub(d_src,  4, "b")
dest_q4b = get_sub(d_dest, 4, "b")

assert src_q4b,  "Q4b not found in SRC"
assert dest_q4b, "Q4b not found in DEST"

print("Q4b UPDATE (direct text update):")
print(f"  OLD uid={dest_q4b['unique_id']} | NEW uid={src_q4b['unique_id']}")

# --- Q4c: add v1/v2 (old=v1 main, new=v2 as or_question) ---
src_q4c  = get_sub(d_src,  4, "c")
dest_q4c = get_sub(d_dest, 4, "c")

assert src_q4c,  "Q4c not found in SRC"
assert dest_q4c, "Q4c not found in DEST"

print("\nQ4c V1/V2 (old=v1 main, new=v2 as or_question):")
print(f"  v1 (main)        uid={dest_q4c.get('unique_id')}")
print(f"  v2 (or_question) uid={src_q4c.get('unique_id')}")

# Build updated q4c: keep old (dest) as main, add new (src) as or_question
updated_q4c = dest_q4c
updated_q4c["or_question"] = {
    "question":       src_q4c.get("question", ""),
    "answer":         src_q4c.get("answer", ""),
    "chapter_number": src_q4c.get("chapter_number", ""),
    "chapter_name":   src_q4c.get("chapter_name", ""),
    "unique_id":      src_q4c.get("unique_id", ""),
}

# --- Patch d_dest Q4 sub_questions ---
for q in d_dest["section_b"]:
    if q.get("q_main") == 4:
        for i, sq in enumerate(q["sub_questions"]):
            if sq.get("label") == "b":
                q["sub_questions"][i] = src_q4b   # direct update
                print("\n  Patched Q4b ✅")
            elif sq.get("label") == "c":
                q["sub_questions"][i] = updated_q4c  # v1/v2
                print("  Patched Q4c ✅")

# --- Backup and save ---
shutil.copy2(DEST_PAPER, DEST_PAPER + ".bak")
print(f"\nBacked up to {DEST_PAPER}.bak")

with open(DEST_PAPER, "w", encoding="utf-8") as f:
    json.dump(d_dest, f, indent=2, ensure_ascii=False)

print(f"✅ Saved updated paper to {DEST_PAPER}")

# --- Verify ---
with open(DEST_PAPER) as f: d_verify = json.load(f)

def get_sub_v(data, q_main, label):
    for q in data.get("section_b", []):
        if q.get("q_main") == q_main:
            for sq in q.get("sub_questions", []):
                if sq.get("label") == label:
                    return sq
    return None

q4b_check = get_sub_v(d_verify, 4, "b")
q4c_check = get_sub_v(d_verify, 4, "c")

print("\nVerification:")
print(f"  Q4b uid: {q4b_check.get('unique_id')} | Q: {q4b_check.get('question','')[:80].replace(chr(10),' ')}")
print(f"  Q4c uid: {q4c_check.get('unique_id')} (main/v1)")
if "or_question" in q4c_check:
    print(f"  Q4c or_question uid: {q4c_check['or_question']['unique_id']} (v2)")
    print(f"  Q4c or_question Q: {q4c_check['or_question']['question'][:80].replace(chr(10),' ')}")
else:
    print("  Q4c has NO or_question — something went wrong!")
