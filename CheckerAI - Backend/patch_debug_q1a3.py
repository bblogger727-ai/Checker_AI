with open("generate_checked_copy_v2.py") as f: text = f.read()
target = "_item_slice_top = q_top_frac"
replacement = "    print(f'[DEBUG] slice for {q_num}: top={q_top_frac:.3f}, bot={q_bot_frac:.3f}, my_order={my_order}')\n    " + target
text = text.replace(target, replacement)
with open("generate_checked_copy_v2.py", "w") as f: f.write(text)
