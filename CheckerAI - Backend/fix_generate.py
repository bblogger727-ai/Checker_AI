import sys

with open("generate_checked_copy_v2.py", "r") as f:
    lines = f.readlines()

new_lines = []
i = 0
while i < len(lines):
    if "first_items_on_page = [it for it in items if it[\"is_first\"]]" in lines[i]:
        new_lines.append("""                # CRITICAL FIX: Include ALL items on this page (even continuations).
                # Continuations won't have a heading in pre_heading_fracs, so they default to 0.0 (top).
                page_q_items = list(items)
                _items_qnums = {it["q_num"] for it in page_q_items}
                _phantom_slots = [
                    {"q_num": qn, "is_first": True, "_phantom": True}
                    for qn in pre_heading_fracs
                    if qn not in _items_qnums
                ]
                page_q_items = page_q_items + _phantom_slots
                if len(page_q_items) > 1:
                    actual_items = [it for it in page_q_items if it["q_num"] in pre_heading_fracs or not it.get("_phantom")]
                    if actual_items:
                        page_q_items = actual_items
                        
                if len(page_q_items) > 1:
                    page_q_items = sorted(
                        page_q_items,
                        key=lambda it: pre_heading_fracs.get(it["q_num"], 0.0 if not it.get("is_first") else 0.5)
                    )
                    _sorted_q_names = [it['q_num'] for it in page_q_items]
                    print(f"    [multi-Q] Sorted page order: {_sorted_q_names} (by heading Y)", flush=True)
                    
                n_items = len(page_q_items)
                my_order = next((idx for idx, it in enumerate(page_q_items) if it["q_num"] == q_num), 0)
""")
        # skip lines until `multi_q_target_y_frac = None`
        while "multi_q_target_y_frac = None" not in lines[i]:
            i += 1
        new_lines.append("                multi_q_target_y_frac = None\n")
        
        while "if ocr_page_text and n_firsts == 1:" not in lines[i]:
            i += 1
        new_lines.append("                if ocr_page_text and n_items == 1:\n")
        i += 1
        continue
        
    if "elif n_firsts > 1:" in lines[i]:
        new_lines.append("                elif n_items > 1:\n")
        new_lines.append("                    # ── Multiple questions on same page: EQUAL-DIVISION slicing ────────\n")
        new_lines.append("                    ink_span = max(0.05, ink_bot - ink_top)\n")
        new_lines.append("                    slice_h  = ink_span / n_items\n")
        new_lines.append("                    q_top_frac  = ink_top + my_order * slice_h\n")
        new_lines.append("                    q_bot_frac  = ink_top + (my_order + 1) * slice_h\n")
        new_lines.append("                    q_top_frac  = min(q_top_frac, ink_bot)\n")
        new_lines.append("                    q_bot_frac  = min(q_bot_frac, ink_bot)\n")
        new_lines.append("                    if n_items == 2:\n")
        new_lines.append("                        multi_q_target_y_frac = 0.16 if my_order == 0 else 0.82\n")
        new_lines.append("                    elif n_items == 3:\n")
        new_lines.append("                        multi_q_target_y_frac = [0.16, 0.55, 0.82][my_order]\n")
        new_lines.append("                    else:\n")
        new_lines.append("                        multi_q_target_y_frac = 0.5\n")
        
        # skip until `else:` block
        while "else:" not in lines[i] or "q_top_frac, q_bot_frac = ink_top, ink_bot" not in lines[i+1]:
            i += 1
        new_lines.append(lines[i])
        i += 1
        new_lines.append(lines[i])
        i += 1
        continue
        
    new_lines.append(lines[i])
    i += 1

with open("generate_checked_copy_v2_temp.py", "w") as f:
    f.writelines(new_lines)
