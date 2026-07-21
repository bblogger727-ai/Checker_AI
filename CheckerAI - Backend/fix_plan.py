import sys

with open("generate_checked_copy_v2.py", "r") as f:
    lines = f.readlines()

new_lines = []
i = 0
while i < len(lines):
    if "start_line, end_line = _find_question_line_bounds(ocr_page_text, q_num)" in lines[i]:
        new_lines.append("""        # Use physical slice bounds instead of brittle text matching for line filtering
        content_idxs = []
        for line_idx in range(total_lines):
            if lines[line_idx].strip():
                raw_frac = (line_idx + 0.5) / total_lines
                y_frac = ink_top + raw_frac * (ink_bot - ink_top)
                if slice_top <= y_frac <= slice_bot:
                    content_idxs.append(line_idx)
""")
        i += 5  # skip the original content_idxs assignment
        continue
    new_lines.append(lines[i])
    i += 1

with open("generate_checked_copy_v2_temp.py", "w") as f:
    f.writelines(new_lines)
