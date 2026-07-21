import sys

with open("generate_checked_copy_v2.py", "r") as f:
    text = f.read()

# 1. Update signature
old_sig = """def _find_feedback_spot_in_q_bounds(
    ocr_page_text: str,
    q_num: str,
    pdf_h: float,
    pdf_w: float,
    page_used_y_fracs: list,
    text_blocks: list,
    ink_top: float = 0.05,
    ink_bot: float = 0.95,
) -> tuple[float, float] | None:"""

new_sig = """def _find_feedback_spot_in_q_bounds(
    ocr_page_text: str,
    q_num: str,
    pdf_h: float,
    pdf_w: float,
    page_used_y_fracs: list,
    text_blocks: list,
    ink_top: float = 0.05,
    ink_bot: float = 0.95,
    slice_top: float = 0.05,
    slice_bot: float = 0.95,
) -> tuple[float, float] | None:"""

text = text.replace(old_sig, new_sig)
print(f"Signature fixed: {new_sig in text}")

# 3. Update caller
old_caller = """                fb_ink_top = _item_slice_top
                fb_ink_bot = _item_slice_bot
                spot = _find_feedback_spot_in_q_bounds(
                    ocr_page_text, q_num, pdf_h, pdf_w, page_used_y_fracs,
                    text_blocks = text_blocks,
                    ink_top     = fb_ink_top,
                    ink_bot     = fb_ink_bot,
                )"""

new_caller = """                spot = _find_feedback_spot_in_q_bounds(
                    ocr_page_text, q_num, pdf_h, pdf_w, page_used_y_fracs,
                    text_blocks = text_blocks,
                    ink_top     = ink_top,
                    ink_bot     = ink_bot,
                    slice_top   = _item_slice_top,
                    slice_bot   = _item_slice_bot,
                )"""

text = text.replace(old_caller, new_caller)
print(f"Caller fixed: {new_caller in text}")

with open("generate_checked_copy_v2.py", "w") as f:
    f.write(text)
