import sys

with open('generate_checked_copy_v2.py') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    new_lines.append(line)
    if "marks_x, marks_y_placed = margin_spot" in line:
        indent = line[:len(line) - len(line.lstrip())]
        new_lines.append(indent + "print('DEBUG margin_spot y_placed:', marks_y_placed, 'q_num:', q_num)\n")
    if "marks_x, marks_y_placed = rect_result[:2]" in line:
        indent = line[:len(line) - len(line.lstrip())]
        new_lines.append(indent + "print('DEBUG rect_result y_placed:', marks_y_placed, 'q_num:', q_num)\n")
    if "marks_x, marks_y_placed = _find_clear_xy(" in line:
        indent = line[:len(line) - len(line.lstrip())]
        new_lines.append(indent + "print('DEBUG clear_xy finding... q_top_frac:', q_top_frac if 'q_top_frac' in locals() else 'None', 'q_num:', q_num)\n")
    if "marks_y_placed = min(max(marks_y_placed, pdf_h * 0.05 + _STAMP_HALF_H)" in line:
        indent = line[:len(line) - len(line.lstrip())]
        new_lines.insert(-1, indent + "print('DEBUG BEFORE CLAMP marks_y_placed:', marks_y_placed, 'q_num:', q_num)\n")

with open('generate_checked_copy_v2_debug.py', 'w') as f:
    f.writelines(new_lines)
