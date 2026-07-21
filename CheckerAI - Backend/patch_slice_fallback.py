with open("generate_checked_copy_v2.py", "r") as f:
    text = f.read()

target = """                elif n_items > 1:
                    # ── Multiple questions on same page: slicing by heading position ────────
                    q_top_frac = ink_top
                    if my_order > 0:
                        q_top_frac = max(ink_top, pre_heading_fracs.get(q_num, ink_top) - 0.05)
                    q_bot_frac = ink_bot
                    if my_order < n_items - 1:
                        next_q = page_q_items[my_order + 1]["q_num"]
                        q_bot_frac = min(ink_bot, pre_heading_fracs.get(next_q, ink_bot) + 0.02)
                    q_bot_frac = max(q_bot_frac, q_top_frac + 0.1)
                    
                    # Hardcode marks placement for pages where exactly two questions start
                    firsts_on_page = [it for it in page_q_items if it.get("is_first") and not it.get("_phantom")]
                    if len(firsts_on_page) == 2 and is_first:"""

replacement = """                elif n_items > 1:
                    # ── Multiple questions on same page: slicing by heading position ────────
                    firsts_on_page = [it for it in page_q_items if it.get("is_first") and not it.get("_phantom")]
                    is_two_firsts = len(firsts_on_page) == 2
                    
                    q_top_frac = ink_top
                    if my_order > 0:
                        fallback_top = 0.50 if is_two_firsts else ink_top
                        q_top_frac = max(ink_top, pre_heading_fracs.get(q_num, fallback_top) - 0.05)
                    q_bot_frac = ink_bot
                    if my_order < n_items - 1:
                        next_q = page_q_items[my_order + 1]["q_num"]
                        fallback_bot = 0.50 if is_two_firsts else ink_bot
                        q_bot_frac = min(ink_bot, pre_heading_fracs.get(next_q, fallback_bot) + 0.02)
                    q_bot_frac = max(q_bot_frac, q_top_frac + 0.1)
                    
                    # Hardcode marks placement for pages where exactly two questions start
                    if is_two_firsts and is_first:"""

text = text.replace(target, replacement)
with open("generate_checked_copy_v2.py", "w") as f:
    f.write(text)
