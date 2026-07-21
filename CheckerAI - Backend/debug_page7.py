import fitz
import cv2
import numpy as np
from PIL import Image
import sys

# Import _get_text_blocks from the script
sys.path.append(".")
from generate_checked_copy_v2 import _get_text_blocks

doc = fitz.open("../15919as.pdf")
page = doc[6] # Page 7
pix = page.get_pixmap(dpi=150)
img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
gray = img.convert("L")

blocks = _get_text_blocks(gray, pix.width, pix.height)
print("Page 7 Text Blocks:")
for b in blocks:
    print(f"  y={b[0]:.3f}, h={b[1]:.3f}")
