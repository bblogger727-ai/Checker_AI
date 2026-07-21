def test_tick(total_lines, ink_top=0.04):
    estimated_ink_bot = min(0.92, ink_top + total_lines * 0.04)
    print(f"Total lines: {total_lines}")
    print(f"Estimated ink bot: {estimated_ink_bot:.2f}")
    
    for L in range(total_lines):
        raw_frac = (L + 0.5) / total_lines
        y_frac = ink_top + raw_frac * (estimated_ink_bot - ink_top)
        print(f"  Line {L+1} -> y_frac: {y_frac:.2f}")

test_tick(8)
print("---")
test_tick(25)
