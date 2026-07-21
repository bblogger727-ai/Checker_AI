import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_pdf import convert_md_to_pdf

dataset_dir = "grading_results/dataset_FR_Manual_Run"
fb_file = f"{dataset_dir}/feedback_final.json"

with open(fb_file) as f:
    fb = json.load(f)

md = "# FR Feedback\n\n"

def render_question(node):
    qid = node.get("question_id", "")
    qnum = node.get("question_number", "")
    sub = node.get("subpart", "")
    ms = node.get("marks_scored", "?")
    mt = node.get("marks", "?")
    feedback = node.get("feedback", {})
    # question_number may be "Q1", "Q2", etc. — strip leading Q if present
    qnum_clean = qnum.lstrip("Q")
    if not sub or sub == qnum or sub == qnum_clean:
        label = f"Q{qnum_clean}"
    else:
        label = f"Q{qnum_clean} ({sub})"
    out = f"## {label}\n"
    out += f"**Marks Scored:** {ms} / {mt}\n\n"
    wwr = feedback.get("what_went_right", "")
    wwwg = feedback.get("what_went_wrong", "")
    conc = feedback.get("conclusion", "")
    if wwr:
        out += f"### What Went Right\n{wwr}\n\n"
    if wwwg:
        out += f"### What Went Wrong\n{wwwg}\n\n"
    if conc:
        out += f"### Conclusion\n{conc}\n\n"
    out += "---\n\n"
    return out

def walk(node):
    global md
    if isinstance(node, dict):
        # It's a question node if it has a feedback key
        if "feedback" in node:
            md += render_question(node)
        else:
            for v in node.values():
                walk(v)
    elif isinstance(node, list):
        for item in node:
            walk(item)

# Only walk the SectionB top-level key (the real data, not "sections")
main = fb.get("SectionB", {})
walk(main)

md_path = f"{dataset_dir}/FR Feedback.md"
pdf_path = f"{dataset_dir}/FR Feedback.pdf"

with open(md_path, "w") as f:
    f.write(md)
print(f"✓ Markdown saved: {md_path}")

convert_md_to_pdf(md_path, pdf_path)
