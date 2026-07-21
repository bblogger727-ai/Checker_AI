with open("generate_checked_copy_v2.py") as f: text = f.read()
target = "page_q_items = list(items)"
replacement = "print(f'\\n[DEBUG] pre_heading_fracs: {pre_heading_fracs}')\n                " + target
text = text.replace(target, replacement)
with open("generate_checked_copy_v2.py", "w") as f: f.write(text)
