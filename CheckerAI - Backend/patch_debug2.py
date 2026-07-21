with open("generate_checked_copy_v2.py") as f: text = f.read()
target = "return result"
replacement = "    print(f'[DEBUG _plan result] {q_num}: {result}')\n    return result"
text = text.replace(target, replacement)

target2 = "n_sel  = len(y_candidates)"
replacement2 = "    print(f'[DEBUG _plan cands] {q_num}: {y_candidates}')\n    " + target2
text = text.replace(target2, replacement2)

with open("generate_checked_copy_v2.py", "w") as f: f.write(text)
