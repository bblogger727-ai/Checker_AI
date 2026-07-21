import sys
sys.path.append('.')
import generate_checked_copy_v2

original_find = generate_checked_copy_v2._find_left_margin_stamp_spot
def mocked_find(gray, img_w, img_h, pdf_w, pdf_h, row_top, row_bot, excluded_px_rows=None):
    print("DEBUG margin_spot called with row_top:", row_top, "row_bot:", row_bot, "img_h:", img_h)
    return original_find(gray, img_w, img_h, pdf_w, pdf_h, row_top, row_bot, excluded_px_rows)

generate_checked_copy_v2._find_left_margin_stamp_spot = mocked_find

generate_checked_copy_v2.generate_checked_copy(
    "/Users/gaureshmantri/Desktop/CheckerAI/15919AS.pdf",
    "grading_results/dataset_15919/grading_final.json",
    "grading_results/dataset_15919/aligned_answers.json",
    "test_out.pdf",
    "test_out_manifest.json"
)
