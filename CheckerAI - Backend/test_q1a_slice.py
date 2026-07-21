import json

aligned = json.load(open("grading_results/dataset_15919/aligned_answers.json"))
ink_top = 0.04
ink_bot = 0.918
pdf_h = 842

items = [
    {"q_num": "1a", "is_first": False, "_phantom": False},
    {"q_num": "1b", "is_first": True, "_phantom": False}
]

# pre_heading_fracs populating logic for Page 2
pre_heading_fracs = {}
# "1b" is not found by PyMuPDF, so _find_heading_y is None
# OCR finds it? 
# In debug3.log, Q1b stamp was at 387. 1 - 387/842 = 0.54.
pre_heading_fracs["1b"] = 0.54

page_q_items = list(items)
n_items = len(page_q_items)
my_order = 0 # 1a
q_num = "1a"

q_top_frac = ink_top
if my_order > 0:
    q_top_frac = max(ink_top, pre_heading_fracs.get(q_num, ink_top) - 0.05)
q_bot_frac = ink_bot
if my_order < n_items - 1:
    next_q = page_q_items[my_order + 1]["q_num"]
    q_bot_frac = min(ink_bot, pre_heading_fracs.get(next_q, ink_bot) + 0.02)

print(f"q_bot_frac for 1a: {q_bot_frac}")
