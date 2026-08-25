import json

src  = "/Users/gaureshmantri/Documents/Secure PDF Extraction/All_Paper_JSONs/Final/IDT_Mock_Paper_3.json"
dest = "/Users/gaureshmantri/Desktop/CheckerAI/All_Paper_JSONs/Final/IDT_Mock_Paper_3.json"

with open(src)  as f: d_src  = json.load(f)
with open(dest) as f: d_dest = json.load(f)

def get_sub(data, q_main, label):
    for q in data.get("section_b", []):
        if q.get("q_main") == q_main:
            for sq in q.get("sub_questions", []):
                if sq.get("label") == label:
                    return sq
    return None

for lbl in ["b", "c"]:
    s_src  = get_sub(d_src,  4, lbl)
    s_dest = get_sub(d_dest, 4, lbl)

    src_uid   = s_src.get("unique_id")  if s_src  else "MISSING"
    dest_uid  = s_dest.get("unique_id") if s_dest else "MISSING"
    src_marks = s_src.get("marks")      if s_src  else "?"
    dest_marks= s_dest.get("marks")     if s_dest else "?"

    src_q  = s_src.get("question",  "")[:500].replace("\n", " ") if s_src  else ""
    dest_q = s_dest.get("question", "")[:500].replace("\n", " ") if s_dest else ""
    src_a  = s_src.get("answer",    "")[:200].replace("\n", " ") if s_src  else ""
    dest_a = s_dest.get("answer",   "")[:200].replace("\n", " ") if s_dest else ""

    same_q = (s_src.get("question","") == s_dest.get("question","")) if (s_src and s_dest) else False
    same_a = (s_src.get("answer","")   == s_dest.get("answer",""))   if (s_src and s_dest) else False

    print(f"\n{'='*70}")
    print(f"Q4{lbl}")
    print(f"  SRC  uid={src_uid}  marks={src_marks}")
    print(f"  DEST uid={dest_uid} marks={dest_marks}")
    print(f"\n  SRC  Q: {src_q}")
    print(f"\n  DEST Q: {dest_q}")
    print(f"\n  SRC  A: {src_a}")
    print(f"\n  DEST A: {dest_a}")
    print(f"\n  Same question? {same_q}")
    print(f"  Same answer?   {same_a}")
