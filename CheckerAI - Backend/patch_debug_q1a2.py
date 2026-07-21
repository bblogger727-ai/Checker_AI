with open("generate_checked_copy_v2.py") as f: text = f.read()
target = "q_bot_frac = min(ink_bot, pre_heading_fracs.get(next_q, ink_bot) + 0.02)"
replacement = "    print(f'[DEBUG next_q] next_q={next_q}, val={pre_heading_fracs.get(next_q, \"NOT_FOUND\")}')\n    " + target
text = text.replace(target, replacement)
with open("generate_checked_copy_v2.py", "w") as f: f.write(text)
