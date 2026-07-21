import fitz
from PIL import Image
import sys

doc = fitz.open("../15919as.pdf")
page = doc[6] # Page 7
pix = page.get_pixmap(dpi=150)
img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
gray = img.convert("L")

px = gray.load()
img_w, img_h = pix.width, pix.height

INK_THR  = 150
MIN_ROW  = max(2, int(img_w * 0.03))
STEP     = 3
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

gaps = []
for i in range(1, len(ink_rows)):
    gap = ink_rows[i] - ink_rows[i-1]
    if gap > 1:
        gaps.append(gap)

print(f"Total ink rows: {len(ink_rows)}")
print(f"Max gap: {max(gaps) if gaps else 0}")
print(f"Avg gap: {sum(gaps)/len(gaps) if gaps else 0}")
print(f"Gaps > 10: {[g for g in gaps if g > 10]}")
