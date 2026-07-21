import re

with open("generate_checked_copy_v2.py", "r") as f:
    text = f.read()

pattern = r"# Prefer just after the question ends.*?return None"
new_logic = """# Prefer near the bottom of the slice
    y_frac = _try_candidate((slice_bot - ink_top) / max(0.01, ink_bot - ink_top))
    if y_frac is not None:
        return pdf_w * 0.08, pdf_h * (1.0 - y_frac)

    # Prefer blank lines within this question's physical slice bounds, starting from the BOTTOM
    blank_lines = []
    for i in range(total_lines):
        if not lines[i].strip():
            y_curr = ink_top + ((i + 0.5) / total_lines) * (ink_bot - ink_top)
            if slice_top <= y_curr <= slice_bot:
                blank_lines.append(i)
                
    for b in reversed(blank_lines):
        y_frac = _try_candidate((b + 0.5) / total_lines)
        if y_frac is not None:
            return pdf_w * 0.08, pdf_h * (1.0 - y_frac)

    # Fallback: scan starting from 90% down the slice, moving upwards
    for offset in range(0, 90, 5):
        frac_in_slice = 0.9 - offset / 100.0
        target_y = slice_top + frac_in_slice * (slice_bot - slice_top)
        raw_frac = (target_y - ink_top) / max(0.01, ink_bot - ink_top)
        y_frac = _try_candidate(raw_frac)
        if y_frac is not None:
            return pdf_w * 0.08, pdf_h * (1.0 - y_frac)

    return None"""

text, n = re.subn(pattern, new_logic, text, flags=re.DOTALL)
print(f"Replaced {n} occurrences of the body.")

with open("generate_checked_copy_v2.py", "w") as f:
    f.write(text)
