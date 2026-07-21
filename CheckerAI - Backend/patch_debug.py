with open("generate_checked_copy_v2.py") as f: text = f.read()
target = "def _plan_annotations_from_ocr("
replacement = target
patch = """
    print(f"[DEBUG _plan] {q_num} on page {page_idx_in_q}: ink=({ink_top:.3f}, {ink_bot:.3f}), slice=({slice_top:.3f}, {slice_bot:.3f})")
"""
text = text.replace("    estimated_ink_bot =", patch + "    estimated_ink_bot =")
with open("generate_checked_copy_v2.py", "w") as f: f.write(text)
