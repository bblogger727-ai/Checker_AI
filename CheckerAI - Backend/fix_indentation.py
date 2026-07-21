with open("generate_checked_copy_v2.py", "r") as f:
    text = f.read()

target = """            if _is_phantom:
                continue



                # ── Marks stamp placement: LEFT MARGIN is the primary target ──"""

replacement = """            if is_first and not _is_phantom:
                # ── Marks stamp placement: LEFT MARGIN is the primary target ──"""

text = text.replace(target, replacement)
with open("generate_checked_copy_v2.py", "w") as f:
    f.write(text)
