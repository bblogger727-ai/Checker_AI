with open("generate_checked_copy_v2.py") as f: text = f.read()
target = "_item_slice_bot = q_bot_frac"
replacement = target + "\n                print(f'[DEBUG SLICE] page={page_num}, q={q_num}, order={my_order}, next={next_q if my_order < n_items - 1 else None}, q_bot={q_bot_frac}', flush=True)"
text = text.replace(target, replacement)
with open("generate_checked_copy_v2.py", "w") as f: f.write(text)
