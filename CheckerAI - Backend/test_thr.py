from PIL import Image
import fitz
import sys
from generate_checked_copy import _render_gray

doc = fitz.open("grading_results/dataset_15193/AFM AS 15193.pdf")
page = doc[4]
gray, img_w, img_h, sx, sy = _render_gray(page)

px = gray.load()

for thr in [100, 120, 150, 180, 200]:
    ink_rows = []
    STEP = 3
    MIN_ROW = max(2, int(img_w * 0.03))
    for y in range(img_h):
        dark = sum(1 for x in range(0, img_w, STEP) if px[x, y] < thr)
        if dark * STEP >= MIN_ROW:
            ink_rows.append(y)
    
    if not ink_rows:
        print(f"thr={thr}: no ink")
        continue
    
    gap_px = max(2, int(img_h * 0.02))
    min_span_px = max(3, int(img_h * 0.03))
    blocks, start, prev = [], ink_rows[0], ink_rows[0]
    for row in ink_rows[1:]:
        if row - prev > gap_px:
            if prev - start >= min_span_px:
                blocks.append((start, prev))
            start, prev = row, row
        else:
            prev = row
    if prev - start >= min_span_px:
        blocks.append((start, prev))
        
    f_blocks = blocks
    if blocks:
        max_span = max(b[1] - b[0] for b in blocks)
        f_blocks = [b for b in blocks if (b[1]-b[0]) >= max_span * 0.30]
        if not f_blocks: f_blocks = blocks
        
    if f_blocks:
        ink_bot = f_blocks[-1][1] / img_h
        print(f"thr={thr}: ink_bot={ink_bot:.3f}")
    
