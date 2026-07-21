with open("generate_checked_copy_v2.py") as f: text = f.read()
target = "y_frac = min(max(y_frac, lower_bound), upper_bound)"
replacement = "        print(f'[DEBUG bounds] {q_num}: y_frac={y_frac:.3f}, slice_bot={slice_bot:.3f}, _ann={_ann_ink_bot:.3f}, upper={upper_bound:.3f}')\n        " + target
text = text.replace(target, replacement)
with open("generate_checked_copy_v2.py", "w") as f: f.write(text)
