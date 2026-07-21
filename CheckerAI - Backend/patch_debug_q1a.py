with open("generate_checked_copy_v2.py") as f: text = f.read()
target = "if heading_y_frac and heading_y_frac > q_top_frac:"
replacement = "    print(f'[DEBUG multi-Q] {q_num}: n_items={n_items} my_order={my_order} q_bot_frac={q_bot_frac}')\n    " + target
text = text.replace(target, replacement)
with open("generate_checked_copy_v2.py", "w") as f: f.write(text)
