with open("generate_checked_copy_v2.py", "r") as f:
    text = f.read()

target1 = """    if ocr_page_text.strip():
        lines       = ocr_page_text.split("\\n")
        total_lines = len(lines)
        start_line, end_line = _find_question_line_bounds(ocr_page_text, q_num)

        content_idxs = [
            i for i in range(start_line + 1, min(end_line, total_lines))
            if lines[i].strip()
        ]"""

replace1 = """    if ocr_page_text.strip():
        lines       = ocr_page_text.split("\\n")
        total_lines = len(lines)

        # Use physical slice bounds instead of brittle text matching for line filtering
        content_idxs = []
        for line_idx in range(total_lines):
            if lines[line_idx].strip():
                raw_frac = (line_idx + 0.5) / total_lines
                y_frac = ink_top + raw_frac * (ink_bot - ink_top)
                if slice_top <= y_frac <= slice_bot:
                    content_idxs.append(line_idx)"""

if target1 in text:
    text = text.replace(target1, replace1)
    print("Replaced target1")
else:
    print("Target1 not found")

target2 = """    start_line, end_line = _find_question_line_bounds(ocr_page_text, q_num)
    MIN_SEP   = 0.09
    BLOCK_CLR = 0.035"""

replace2 = """    MIN_SEP   = 0.09
    BLOCK_CLR = 0.035"""

if target2 in text:
    text = text.replace(target2, replace2)
    print("Replaced target2")
else:
    print("Target2 not found")

target3 = """    # Find all empty visual gaps in the OCR text
    for i in range(start_line, min(end_line - 1, total_lines - 1)):
        if not lines[i].strip():
            continue
            
        for j in range(i + 1, min(end_line, total_lines)):
            if lines[j].strip():"""

replace3 = """    # Find all empty visual gaps in the OCR text that are inside our slice
    for i in range(total_lines - 1):
        if not lines[i].strip():
            continue
        
        raw_frac_curr = (i + 0.5) / total_lines
        y_frac_curr = ink_top + raw_frac_curr * (ink_bot - ink_top)
        
        # Must be inside the physical slice assigned to this question
        # Since _get_non_colliding_y is not passed slice_top/bot directly yet,
        # wait! _get_non_colliding_y DOES NOT take slice_top/bot!"""

if target3 in text:
    text = text.replace(target3, replace3)
    print("Replaced target3")
else:
    print("Target3 not found")

with open("generate_checked_copy_v2.py", "w") as f:
    f.write(text)
