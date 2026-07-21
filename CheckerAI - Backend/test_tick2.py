import fitz
import sys
import json
sys.path.append(".")
from generate_checked_copy_v2 import _plan_annotations_from_ocr

with open("grading_results/dataset_15919/ocr_output.txt") as f:
    text = f.read()

pages = text.split("=== Page ")
page7_text = pages[7].split("\n", 1)[1] if len(pages) > 7 else ""
print("OCR length:", len(page7_text.split("\n")))

candidates = _plan_annotations_from_ocr(
    ocr_page_text=page7_text,
    q_num="5b",
    pdf_w=595, pdf_h=842,
    marks_obtained=3.5, marks_total=4.0,
    page_idx_in_q=0, total_pages=1,
    page_used_y_fracs=[],
    ink_top=0.040, # Ah!!! Wait! I need to know what ink_top is!
    ink_bot=0.918,
    slice_top=0.04,
    slice_bot=0.918
)
print("Candidates:", candidates)
