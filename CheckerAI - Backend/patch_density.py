with open("generate_checked_copy_v2.py", "r") as f:
    text = f.read()

target = """    all_d    = sorted(d for _, d in row_densities)
    median_d = all_d[len(all_d) // 2]
    hw_threshold = max(0.01, median_d * 2)

    last_hw_y = y_scan_start
    for y, d in row_densities:
        if d >= hw_threshold:
            last_hw_y = y"""

replacement = """    all_d    = sorted(d for _, d in row_densities)
    median_d = all_d[len(all_d) // 2]
    # Use a much more reasonable threshold. If the median is high, we don't demand 2x the median.
    # 1.5% dark pixels in a row is typically enough to indicate handwriting.
    hw_threshold = max(0.015, min(0.03, median_d * 1.5))

    last_hw_y = y_scan_start
    for y, d in row_densities:
        if d >= hw_threshold:
            last_hw_y = y"""

text = text.replace(target, replacement)
with open("generate_checked_copy_v2.py", "w") as f:
    f.write(text)
