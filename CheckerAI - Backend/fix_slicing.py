import sys

with open("generate_checked_copy_v2.py", "r") as f:
    lines = f.readlines()

new_lines = []
i = 0
while i < len(lines):
    if "elif n_items > 1:" in lines[i]:
        new_lines.append(lines[i])
        i += 1
        new_lines.append("                    # ── Multiple questions on same page: slicing by heading position ────────\n")
        new_lines.append("                    q_top_frac = ink_top\n")
        new_lines.append("                    if my_order > 0:\n")
        new_lines.append("                        q_top_frac = max(ink_top, pre_heading_fracs.get(q_num, ink_top) - 0.05)\n")
        new_lines.append("                    q_bot_frac = ink_bot\n")
        new_lines.append("                    if my_order < n_items - 1:\n")
        new_lines.append("                        next_q = page_q_items[my_order + 1][\"q_num\"]\n")
        new_lines.append("                        q_bot_frac = min(ink_bot, pre_heading_fracs.get(next_q, ink_bot) + 0.02)\n")
        new_lines.append("                    q_bot_frac = max(q_bot_frac, q_top_frac + 0.1)\n")
        new_lines.append("                    multi_q_target_y_frac = q_top_frac + 0.05\n")
        
        # skip lines until `else:` block (which sets `q_top_frac, q_bot_frac = ink_top, ink_bot`)
        while "else:" not in lines[i] or "q_top_frac, q_bot_frac = ink_top, ink_bot" not in lines[i+1]:
            i += 1
        
        # we're at else:
        continue
        
    new_lines.append(lines[i])
    i += 1

with open("generate_checked_copy_v2_temp.py", "w") as f:
    f.writelines(new_lines)
