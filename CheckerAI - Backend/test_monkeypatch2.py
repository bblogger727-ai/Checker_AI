import sys
sys.path.append('.')
import generate_checked_copy_v2

original_bounds = generate_checked_copy_v2._find_question_line_bounds
def mocked_bounds(text, q_num):
    start, end = original_bounds(text, q_num)
    if '1b' in q_num:
        print("DEBUG bounds for", q_num, "start:", start, "total:", len(text.split('\n')) if text else 0)
    return start, end
generate_checked_copy_v2._find_question_line_bounds = mocked_bounds

original_parse = generate_checked_copy_v2._parse_ocr_page
def mocked_parse(path, p_num):
    text = original_parse(path, p_num)
    print("DEBUG parsed OCR for page", p_num, "len:", len(text))
    return text
generate_checked_copy_v2._parse_ocr_page = mocked_parse

generate_checked_copy_v2.generate_checked_copy(
    "/Users/gaureshmantri/Desktop/CheckerAI/15919AS.pdf",
    "grading_results/dataset_15919/grading_final.json",
    "grading_results/dataset_15919/aligned_answers.json",
    "test_out.pdf",
    "test_out_manifest.json"
)
