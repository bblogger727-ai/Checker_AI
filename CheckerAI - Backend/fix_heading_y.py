import re

with open("generate_checked_copy_v2.py", "r") as f:
    text = f.read()

# We need to move:
# heading_y = None
# heading_y_frac = None
# if is_first:
#     heading_y = _find_heading_y(...)
#     if heading_y:
#         heading_y_frac = 1.0 - heading_y / pdf_h
#
# ABOVE the slice computation.

def fix():
    global text
    
    # 1. find the block
    block_pattern = r"            # ── Marks stamp on first page of each answer ───────────────────────\n            heading_y = None\n            heading_y_frac = None\n            if is_first:\n                heading_y = _find_heading_y\(\n                    fitz_page, gray, img_w, img_h, pdf_h, q_num, ocr_text_path\n                \)\n                if heading_y:\n                    heading_y_frac = 1.0 - heading_y / pdf_h"
    
    match = re.search(block_pattern, text)
    if not match:
        print("Could not find block")
        return
        
    block_text = match.group(0)
    
    # 2. remove the block
    text = text[:match.start()] + text[match.end():]
    
    # 3. insert the block before '            # ── Pre-compute per-question vertical slices when page is shared ─'
    insert_pattern = r"            # ── Pre-compute per-question vertical slices when page is shared ─"
    
    match = re.search(insert_pattern, text)
    if not match:
        print("Could not find insert point")
        return
        
    text = text[:match.start()] + block_text + "\n\n" + text[match.start():]
    
    with open("generate_checked_copy_v2.py", "w") as f:
        f.write(text)

fix()
