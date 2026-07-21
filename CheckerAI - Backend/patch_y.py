def _get_non_colliding_y(y_frac, page_used, ink_top, ink_bot, min_sep):
    candidates = [y_frac]
    step = min_sep * 0.4
    for offset in range(1, 40):
        candidates.append(y_frac + offset * step)
        candidates.append(y_frac - offset * step)
    
    for c in candidates:
        if c < ink_top or c > ink_bot - 0.02:
            continue
        if all(abs(c - u) >= min_sep for u in page_used):
            return c
    return None
