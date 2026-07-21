import sys
import re

with open("generate_checked_copy_v2.py", "r") as f:
    text = f.read()

old_logic = """    # ── Step 1: build candidate Y-fracs from OCR lines ───────────────────────
    y_candidates: list[float] = []
    
    # ── Determine True Ink Bottom from Text Blocks ───────────────────────────
    # Tesseract output text doesn't contain trailing newlines, so we can't reliably
    # use line counts to find the bottom of the handwritten text on continuation pages.
    # We use the explicitly passed text_blocks to find the true lowest ink point.
    if text_blocks:
        tb_bot = text_blocks[-1][0] + text_blocks[-1][1] / 2
        # Use whichever is tighter (smaller), and add a 2% buffer.
        ink_bot = min(ink_bot, tb_bot + 0.02)

    if ocr_page_text.strip():
        lines       = ocr_page_text.split("\\n")
        total_lines = len(lines)
        # Use physical slice bounds instead of brittle text matching for line filtering
        content_idxs = []
        for line_idx in range(total_lines):
            if lines[line_idx].strip():
                raw_frac = (line_idx + 0.5) / total_lines
                y_frac = ink_top + raw_frac * (ink_bot - ink_top)
                if slice_top <= y_frac <= slice_bot:
                    content_idxs.append(line_idx)

        if content_idxs:
            # Scale down max_ann if there are very few lines
            if len(content_idxs) <= 8:
                max_ann = 1
            elif len(content_idxs) <= 15:
                max_ann = min(max_ann, 2)

            # Pick evenly-spaced content lines
            if len(content_idxs) <= max_ann:
                selected = content_idxs
            elif max_ann == 1:
                # If only one annotation on a sparse page, put it near the middle, not the very top
                selected = [content_idxs[len(content_idxs) // 2]]
            else:
                step     = len(content_idxs) / max_ann
                selected = [content_idxs[int(i * step)] for i in range(max_ann)]

            for line_idx in selected:
                raw_frac = (line_idx + 0.5) / total_lines
                y_frac   = ink_top + raw_frac * (ink_bot - ink_top)
                
                # Target the central area (20% to 80%) of the question's slice
                # We NO LONGER clamp this, because content_idxs strictly filters lines inside the slice!
                # Clamping them pushed legitimate boundary ticks into a clustered mess.
                
                # Never exceed the last written line
                y_frac   = min(y_frac, ink_bot - 0.02)
                y_candidates.append(y_frac)

    # ── Step 2: fallback to text_blocks when OCR gave nothing ─────────────────
    # Handles pages that are densely written but have no OCR coverage.
    if not y_candidates and text_blocks:
        # Filter text blocks to those strictly within our slice
        slice_blocks = [b for b in text_blocks if slice_top <= b[0] <= slice_bot]
        if slice_blocks:
            if len(slice_blocks) <= 2:
                max_ann = 1
            elif len(slice_blocks) <= 4:
                max_ann = min(max_ann, 2)

            if len(slice_blocks) <= max_ann:
                selected = slice_blocks
            elif max_ann == 1:
                selected = [slice_blocks[len(slice_blocks) // 2]]
            else:
                step     = len(slice_blocks) / max_ann
                selected = [slice_blocks[int(i * step)] for i in range(max_ann)]

            for b in selected:
                y_candidates.append(b[0])"""

new_logic = """    y_candidates: list[float] = []
    
    # ── Use Text Blocks for Physical Y-Placement ───────────────────────────
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
            pass"""

if old_logic in text:
    text = text.replace(old_logic, new_logic)
    with open("generate_checked_copy_v2.py", "w") as f:
        f.write(text)
    print("Success: Tick placement logic successfully rewritten.")
else:
    print("Error: Could not find old_logic block.")
