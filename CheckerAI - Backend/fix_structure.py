import re

with open("generate_checked_copy_v2.py", "r") as f:
    text = f.read()

# I will find the 'for item in items:' loop.
# It starts around line 2164.

def fix():
    global text
    
    # 1. We want to extract the slice logic block.
    start_marker = "                # ── Pre-compute per-question vertical slices when page is shared ─"
    end_marker = "                if _is_phantom:\n                    continue"
    
    # Wait, _is_phantom is evaluated at line 2187: _is_phantom = item.get("_phantom", False)
    
    # Let's just use Python's built-in tools to do precise line extraction.
    lines = text.split('\n')
    
    # Find start and end indices of the slice block
    start_idx = -1
    for i, line in enumerate(lines):
        if "── Pre-compute per-question vertical slices when page is shared ─" in line:
            start_idx = i
            break
            
    end_idx = -1
    for i in range(start_idx, len(lines)):
        if "if _is_phantom:" in line:
            # this is inside if is_first:
            pass
        if "stamp_row_top = max(0,      int(q_top_frac * img_h))" in lines[i]:
            end_idx = i - 2  # The blank line before stamp_row_top
            break
            
    # Extract the block
    slice_block_lines = lines[start_idx:end_idx]
    
    # De-indent the slice block by 4 spaces
    deindented_slice_block = []
    for line in slice_block_lines:
        if line.startswith("    "):
            deindented_slice_block.append(line[4:])
        else:
            deindented_slice_block.append(line)
            
    # Remove the block from its original location
    lines = lines[:start_idx] + lines[end_idx:]
    
    # Now find where to insert it!
    # We want to insert it BEFORE `heading_y = None` (line 2195).
    # Let's find `heading_y = None`.
    insert_idx = -1
    for i, line in enumerate(lines):
        if "heading_y = None" in line and "heading_y_frac = None" in lines[i+1]:
            insert_idx = i - 1
            break
            
    # Insert the block
    lines = lines[:insert_idx] + deindented_slice_block + [""] + lines[insert_idx:]
    
    with open("generate_checked_copy_v2.py", "w") as f:
        f.write('\n'.join(lines))

fix()
