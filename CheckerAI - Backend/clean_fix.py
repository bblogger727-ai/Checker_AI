with open("generate_checked_copy_v2.py", "r") as f:
    text = f.read()

# Fix 1: dangling bracket
text = text.replace("""                if slice_top <= y_frac <= slice_bot:
                    content_idxs.append(line_idx)
        ]""", """                if slice_top <= y_frac <= slice_bot:
                    content_idxs.append(line_idx)""")

# Fix 2: _get_non_colliding_y
import re

bad_block = """    if total_lines == 0:
        return None

        # Use physical slice bounds instead of brittle text matching for line filtering
        content_idxs = []
        for line_idx in range(total_lines):
            if lines[line_idx].strip():
                raw_frac = (line_idx + 0.5) / total_lines
                y_frac = ink_top + raw_frac * (ink_bot - ink_top)
                if slice_top <= y_frac <= slice_bot:
                    content_idxs.append(line_idx)
        if not text_blocks:"""

good_block = """    if total_lines == 0:
        return None

    MIN_SEP   = 0.09
    BLOCK_CLR = 0.035

    def _is_clear_of_blocks(y_frac):
        if not text_blocks:"""

text = text.replace(bad_block, good_block)

bad_gap = """    # Find all empty visual gaps in the OCR text
    for i in range(start_line, min(end_line - 1, total_lines - 1)):
        if not lines[i].strip():
            continue
            
        for j in range(i + 1, min(end_line, total_lines)):
            if lines[j].strip():"""

good_gap = """    # Find all empty visual gaps in the OCR text that are inside our slice
    # Note: _get_non_colliding_y does not receive slice_top/bot!
    # So we must just search the whole page (or pass them in).
    # For now, we search the whole page and the caller (which has the slice) handles it.
    for i in range(0, total_lines - 1):
        if not lines[i].strip():
            continue
            
        for j in range(i + 1, total_lines):
            if lines[j].strip():"""

# Wait, we need to find the correct bad_gap. It might be different if _find_question_line_bounds is missing.
# Let's just fix it manually if it exists.
if bad_gap in text:
    text = text.replace(bad_gap, good_gap)

# What about start_line in _get_non_colliding_y?
# We need to make sure start_line, end_line is not used.
# Since we replaced bad_gap, we just need to fix start_line, end_line definition if it's there.
# It seems it was removed by the bad replace!
# So good_gap should work.

with open("generate_checked_copy_v2.py", "w") as f:
    f.write(text)
