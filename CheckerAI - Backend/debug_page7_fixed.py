import fitz
import cv2
import numpy as np
from PIL import Image
import sys

def _get_text_blocks(gray: Image.Image, img_w: int, img_h: int) -> list:
    px = gray.load()

    INK_THR  = 150          # catches handwriting, ignores very faint shadows
    MIN_ROW  = max(2, int(img_w * 0.03))   # 3 % of row width
    STEP     = 3
    # Skip the very bottom 8 % — scanner border / page-edge shadow
    y_end    = int(img_h * 0.92)

    ink_rows = []
    x_start = int(img_w * 0.1)
    x_end = int(img_w * 0.9)
    for y in range(img_h):
        if y >= y_end:
            break
        dark = sum(1 for x in range(x_start, x_end, STEP) if px[x, y] < INK_THR)
        if dark * STEP >= MIN_ROW:
            ink_rows.append(y)

    if not ink_rows:
        return []

    gap_px      = max(2, int(img_h * 0.02))
    min_span_px = max(3, int(img_h * 0.03))

    blocks = []
    start_y = ink_rows[0]
    last_y  = ink_rows[0]

    for y in ink_rows[1:]:
        if y - last_y > gap_px:
            span = last_y - start_y
            if span >= min_span_px:
                center = start_y + span / 2.0
                blocks.append((center / img_h, span / img_h))
            start_y = y
        last_y = y

    span = last_y - start_y
    if span >= min_span_px:
        center = start_y + span / 2.0
        blocks.append((center / img_h, span / img_h))

    return blocks

doc = fitz.open("../15919as.pdf")
page = doc[6] # Page 7
pix = page.get_pixmap(dpi=150)
img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
gray = img.convert("L")

blocks = _get_text_blocks(gray, pix.width, pix.height)
print("Page 7 Fixed Text Blocks:")
for b in blocks:
    print(f"  y={b[0]:.3f}, h={b[1]:.3f}")
