import json
from PIL import Image
import fitz
import sys
from generate_checked_copy import _get_text_blocks, _render_gray
doc = fitz.open("grading_results/dataset_15193/AFM AS 15193.pdf")
page = doc[4]
gray, img_w, img_h, sx, sy = _render_gray(page)
text_blocks = _get_text_blocks(gray, img_w, img_h)
print(f"Blocks: {text_blocks}")
max_span = max(b[1] for b in text_blocks)
f_blocks = [b for b in text_blocks if b[1] >= max_span * 0.30]
print(f"Filtered: {f_blocks}")
ink_top = max(0.04, min(b[0] - b[1]/2 for b in f_blocks))
ink_bot = min(0.96, max(b[0] + b[1]/2 for b in f_blocks))
print(f"ink_top={ink_top} ink_bot={ink_bot}")
