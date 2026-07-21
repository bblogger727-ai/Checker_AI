"""
Checked copy annotation service.

Generates a marked-up copy of the student's original answer PDF by placing
marks and simple red tick/cross annotations near detected question numbers.
"""

import io
import os
import random
from pathlib import Path

import pytesseract
from pdf2image import convert_from_path
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


SERVICE_DIR = Path(__file__).resolve().parent
APP_DIR = SERVICE_DIR.parent
BACKEND_DIR = APP_DIR.parent
FONT_PATH = BACKEND_DIR / "IndieFlower-Regular.ttf"


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value).strip("_")


def checked_copy_path(student_id: int, student_name: str, output_dir: str) -> str:
    safe_name = _safe_filename(student_name) or "student"
    return os.path.join(output_dir, f"{safe_name}_{student_id}_checked_copy.pdf")


def register_font() -> str:
    if FONT_PATH.exists():
        pdfmetrics.registerFont(TTFont("Handwriting", str(FONT_PATH)))
        return "Handwriting"
    return "Helvetica"


def scan_pdf_locations(pdf_path: str, page_dims: list[tuple[float, float]]) -> dict[tuple[str, str], tuple[int, float, float]]:
    images = convert_from_path(pdf_path)
    locations = {}
    current_section = "SectionA"

    for page_idx, image in enumerate(images):
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        pdf_w, pdf_h = page_dims[page_idx] if page_idx < len(page_dims) else A4
        scale_x = pdf_w / image.width
        scale_y = pdf_h / image.height

        for idx, raw_text in enumerate(data["text"]):
            text = raw_text.strip()
            if not text:
                continue

            try:
                confidence = int(float(data["conf"][idx]))
            except (TypeError, ValueError):
                confidence = -1
            if confidence < 30:
                continue

            if "Section" in text and idx + 1 < len(data["text"]):
                next_text = data["text"][idx + 1].strip().upper()
                if "A" in next_text:
                    current_section = "SectionA"
                elif "B" in next_text:
                    current_section = "SectionB"

            question_number = None
            if text.isdigit() and idx + 1 < len(data["text"]) and data["text"][idx + 1].strip() in [")", "."]:
                question_number = text
            elif text.endswith((")", ".")) and text[:-1].isdigit():
                question_number = text[:-1]
            elif text.lower().startswith("q") and text[1:].isdigit():
                question_number = text[1:]

            if question_number:
                x = data["left"][idx] * scale_x
                y_from_top = data["top"][idx] * scale_y
                y = pdf_h - y_from_top
                locations.setdefault((current_section, question_number), (page_idx, x, y))

    return locations


def draw_tick(mark_canvas, x: float, y: float):
    mark_canvas.saveState()
    mark_canvas.translate(x, y)
    mark_canvas.rotate(random.uniform(-15, 15))
    mark_canvas.scale(random.uniform(0.9, 1.1), random.uniform(0.9, 1.1))
    mark_canvas.setStrokeColor(colors.red)
    mark_canvas.setLineWidth(2)

    path = mark_canvas.beginPath()
    path.moveTo(-5, 5)
    path.lineTo(0, 0)
    path.lineTo(10, 15)
    mark_canvas.drawPath(path, stroke=1, fill=0)
    mark_canvas.restoreState()


def draw_cross(mark_canvas, x: float, y: float):
    mark_canvas.saveState()
    mark_canvas.translate(x, y)
    mark_canvas.rotate(random.uniform(-15, 15))
    mark_canvas.setStrokeColor(colors.red)
    mark_canvas.setLineWidth(2)

    path = mark_canvas.beginPath()
    path.moveTo(-8, -8)
    path.lineTo(8, 8)
    path.moveTo(-8, 8)
    path.lineTo(8, -8)
    mark_canvas.drawPath(path, stroke=1, fill=0)
    mark_canvas.restoreState()


def _iter_graded_items(grading_json: dict):
    graded_answers = grading_json.get("graded_answers", {})
    for section, section_data in graded_answers.items():
        if not isinstance(section_data, dict):
            continue

        for group_key, group_content in section_data.items():
            if not isinstance(group_content, dict):
                continue

            if group_key == "MCQ":
                for sub_id, item in group_content.items():
                    if isinstance(item, dict):
                        yield section, str(sub_id), item, 0
                continue

            question_number = group_key.replace("Q", "")
            if "marks_obtained" in group_content:
                yield section, question_number, group_content, 0
                continue

            for stack_idx, item in enumerate(group_content.values()):
                if isinstance(item, dict):
                    yield section, question_number, item, stack_idx


def generate_checked_copy_pdf(answer_pdf_path: str, grading_json: dict, output_path: str) -> str:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    reader = PdfReader(answer_pdf_path)
    page_dims = [(float(page.mediabox.width), float(page.mediabox.height)) for page in reader.pages]
    locations = scan_pdf_locations(answer_pdf_path, page_dims)
    font_name = register_font()

    packet = io.BytesIO()
    mark_canvas = canvas.Canvas(packet)

    for page_idx, (width, height) in enumerate(page_dims):
        mark_canvas.setPageSize((width, height))
        mark_canvas.setFont(font_name, 16)
        mark_canvas.setFillColor(colors.red)

        for section, question_number, item, stack_idx in _iter_graded_items(grading_json):
            location_key = (section, question_number)
            if location_key not in locations:
                location_key = ("SectionA", question_number) if ("SectionA", question_number) in locations else location_key
                location_key = ("SectionB", question_number) if ("SectionB", question_number) in locations else location_key

            if location_key not in locations:
                continue

            location_page, x, y = locations[location_key]
            if location_page != page_idx:
                continue

            marks = float(item.get("marks_obtained", 0) or 0)
            total = float(item.get("marks_total", 0) or 0)
            draw_x = x - 50 + random.uniform(-2, 2)
            draw_y = y - (stack_idx * 30) + random.uniform(-2, 2)

            if marks == 0:
                draw_cross(mark_canvas, draw_x, draw_y)
            else:
                draw_tick(mark_canvas, draw_x, draw_y)

            score_text = f"+{marks:g}" if marks > 0 else "0"
            if total:
                score_text = f"{score_text}/{total:g}"
            mark_canvas.drawString(draw_x - 34, draw_y, score_text)

        mark_canvas.showPage()

    mark_canvas.save()
    packet.seek(0)
    overlay_pdf = PdfReader(packet)

    writer = PdfWriter()
    for idx, page in enumerate(reader.pages):
        if idx < len(overlay_pdf.pages):
            page.merge_page(overlay_pdf.pages[idx])
        writer.add_page(page)

    with open(output_path, "wb") as output_file:
        writer.write(output_file)

    return output_path
