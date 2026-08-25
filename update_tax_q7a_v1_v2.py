"""
Update TAX_Mock_Paper_1.json in All_Paper_JSONs/Inter:
- Keep old Q7a (BQ-7A) as the main/v1 question
- Add new Q7a (23-T-12, Raghav Ltd GSTR-3B) as or_question / v2
"""
import json, copy, shutil, os

ALL_PAPER = "/Users/gaureshmantri/Desktop/CheckerAI/All_Paper_JSONs/Inter/TAX_Mock_Paper_1.json"
OLD_PAPER  = "/Users/gaureshmantri/Desktop/CheckerAI/Inter/TAX_Mock_Paper_1.json"
SEC_PAPER  = "/Users/gaureshmantri/Documents/Secure PDF Extraction/All_Paper_JSONs/Inter/TAX_Mock_Paper_1.json"

with open(ALL_PAPER) as f: d_all = json.load(f)
with open(OLD_PAPER)  as f: d_old = json.load(f)
with open(SEC_PAPER)  as f: d_sec = json.load(f)

# --- Extract the two Q7a sub-question dicts ---
def get_q_sub(data, q_main, label):
    for q in data["section_b"]:
        if q["q_main"] == q_main:
            for sq in q["sub_questions"]:
                if sq["label"] == label:
                    return copy.deepcopy(sq)
    return None

old_q7a = get_q_sub(d_old, 7, "a")  # BQ-7A  (v1 — old question)
new_q7a = get_q_sub(d_sec, 7, "a")  # 23-T-12 (v2 — new question)

assert old_q7a, "Could not find old Q7a in Inter/TAX_Mock_Paper_1.json"
assert new_q7a, "Could not find new Q7a in Secure PDF TAX_Mock_Paper_1.json"

print(f"v1 (main) uid : {old_q7a['unique_id']}")
print(f"v2 (or_question) uid: {new_q7a['unique_id']}")

# --- Build updated sub_question ---
updated_q7a = old_q7a  # v1 stays as primary
updated_q7a["or_question"] = {
    "question":       new_q7a.get("question", ""),
    "answer":         new_q7a.get("answer", ""),
    "chapter_number": new_q7a.get("chapter_number", ""),
    "chapter_name":   new_q7a.get("chapter_name", ""),
    "unique_id":      new_q7a.get("unique_id", ""),
}

# --- Patch d_all Q7 sub_questions ---
patched = False
for q in d_all["section_b"]:
    if q["q_main"] == 7:
        for i, sq in enumerate(q["sub_questions"]):
            if sq["label"] == "a":
                q["sub_questions"][i] = updated_q7a
                patched = True
                break

assert patched, "Could not find Q7a in All_Paper_JSONs to patch!"

# --- Backup then save ---
shutil.copy2(ALL_PAPER, ALL_PAPER + ".bak")
print(f"Backed up to {ALL_PAPER}.bak")

with open(ALL_PAPER, "w", encoding="utf-8") as f:
    json.dump(d_all, f, indent=2, ensure_ascii=False)

print(f"✅ Saved updated paper to {ALL_PAPER}")

# --- Verify ---
with open(ALL_PAPER) as f: d_verify = json.load(f)
q7a_check = get_q_sub(d_verify, 7, "a")
print(f"\nVerification:")
print(f"  Q7a main uid     : {q7a_check['unique_id']}")
print(f"  Q7a or_question uid: {q7a_check['or_question']['unique_id']}")
print(f"  Q7a main Q (first 80): {q7a_check['question'][:80].replace(chr(10),' ')}")
print(f"  Q7a or Q (first 80): {q7a_check['or_question']['question'][:80].replace(chr(10),' ')}")
