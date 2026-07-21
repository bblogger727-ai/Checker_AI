import re

with open("generate_checked_copy_v2.py", "r") as f:
    text = f.read()

# We want to replace everything from:
#     # ── Step 1: Use Text Blocks for Physical Y-Placement ───────────────────────────
# all the way to the start of:
#     # ── Step 3: Check for collisions ──────────────────────────────────────────────

start_marker = "    # ── Step 1: Use Text Blocks for Physical Y-Placement ───────────────────────────"
end_marker = "    # ── Step 3: Check for collisions ──────────────────────────────────────────────"

if start_marker in text and end_marker in text:
    start_idx = text.find(start_marker)
    end_idx = text.find(end_marker)
    
    new_logic = """    # ── Step 1: Use Text Blocks for Physical Y-Placement ───────────────────────────
    y_candidates: list[float] = []
    
    # We NO LONGER use OCR text for Y-coordinate placement. OCR interpolates evenly
    # across the entire page, completely ignoring blank spaces (e.g. footers), which 
    # causes ticks to be placed incorrectly (e.g. after content finishes).
    if text_blocks:
        tb_bot = text_blocks[-1][0] + text_blocks[-1][1] / 2
        # Use whichever is tighter (smaller), and add a 2% buffer.
        ink_bot = min(ink_bot, tb_bot + 0.02)

        # Filter text blocks strictly within our question's slice AND outside the banned zones
        safe_blocks = []
        for b in text_blocks:
            y_frac = b[0]
            if slice_top <= y_frac <= slice_bot:
                # User specifically banned the top 20% and bottom 15% of the page
                if 0.20 <= y_frac <= 0.85:
                    safe_blocks.append(y_frac)
                    
        if safe_blocks:
            # Scale down max_ann if there are very few blocks
            if len(safe_blocks) <= 8:
                max_ann = 1
            elif len(safe_blocks) <= 15:
                max_ann = min(max_ann, 2)
                
            # Pick evenly-spaced content blocks
            if len(safe_blocks) <= max_ann:
                selected_y = safe_blocks
            elif max_ann == 1:
                # If only one annotation, put it near the middle
                selected_y = [safe_blocks[len(safe_blocks) // 2]]
            else:
                step = len(safe_blocks) / max_ann
                selected_y = [safe_blocks[int(i * step)] for i in range(max_ann)]
                
            for y_frac in selected_y:
                # Never exceed the last written line
                y_frac = min(y_frac, ink_bot - 0.02)
                y_candidates.append(y_frac)
        else:
            # Entire question fell in a ban zone or has no physical blocks inside the slice
            pass

"""
    
    new_text = text[:start_idx] + new_logic + text[end_idx:]
    with open("generate_checked_copy_v2.py", "w") as f:
        f.write(new_text)
    print("Successfully replaced tick placement logic!")
else:
    print("Could not find markers.")
