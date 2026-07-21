#!/usr/bin/env python3
"""Generate PDF grading reports for both datasets."""
import json
import os
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer


def extract_graded_items(graded_answers):
    """Recursively extract (question_label, marks_obtained, marks_total, feedback) from nested grading JSON."""
    items = []

    def walk(obj, prefix=""):
        if isinstance(obj, dict):
            # If this dict has 'marks_obtained', it's a leaf graded item
            if "marks_obtained" in obj:
                label = prefix.strip(".")
                marks = obj.get("marks_obtained", 0)
                total = obj.get("marks_total", 0)
                feedback = obj.get("feedback", "")
                # Skip OR alternatives that were not attempted (0/0)
                if total == 0 and obj.get("skipped_or_alternative"):
                    return
                items.append((label, marks, total, feedback))
            else:
                for key in obj:
                    # Build a readable label
                    new_prefix = f"{prefix}.{key}" if prefix else key
                    walk(obj[key], new_prefix)

    for section_name in sorted(graded_answers.keys()):
        section = graded_answers[section_name]
        walk(section, section_name)

    return items


def deduplicate_label(label):
    """Clean up labels like 'SectionB.Q1.Q1' -> 'Q1', 'SectionB.Q2.a.a' -> 'Q2(a)', 'SectionA.MCQ.1' -> 'MCQ 1'."""
    parts = label.split(".")
    # Remove 'SectionA' / 'SectionB' prefix
    if parts and parts[0].startswith("Section"):
        section_letter = parts[0].replace("Section", "")
        parts = parts[1:]
    else:
        section_letter = ""

    # Deduplicate consecutive identical parts: Q1.Q1 -> Q1, a.a -> a
    deduped = []
    for p in parts:
        if not deduped or deduped[-1] != p:
            deduped.append(p)

    # Build readable label
    if not deduped:
        return label

    if deduped[0] == "MCQ":
        return f"MCQ {deduped[1]}" if len(deduped) > 1 else "MCQ"

    # e.g. ['Q2', 'a'] -> 'Q2(a)', ['Q1'] -> 'Q1'
    base = deduped[0]
    if len(deduped) > 1:
        sub = deduped[1]
        return f"{base}({sub})"
    return base


def wrap_text(text, max_len=120):
    """Truncate feedback for table display."""
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def generate_pdf(grading_json_path, output_pdf_path, title):
    """Generate a tabular PDF report from grading results."""
    with open(grading_json_path) as f:
        data = json.load(f)

    meta = data.get("metadata", {})
    total_obtained = meta.get("total_marks_obtained", 0)
    graded = data.get("graded_answers", {})
    items = extract_graded_items(graded)

    # Build PDF
    doc = SimpleDocTemplate(
        output_pdf_path,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=20 * mm,
        bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=6,
        alignment=1,  # center
    )
    total_style = ParagraphStyle(
        "TotalMarks",
        parent=styles["Heading2"],
        fontSize=13,
        spaceAfter=12,
        alignment=1,
    )
    cell_style = ParagraphStyle(
        "CellText",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
    )
    header_style = ParagraphStyle(
        "HeaderText",
        parent=styles["Normal"],
        fontSize=9,
        leading=11,
        textColor=colors.whitesmoke,
    )

    elements = []
    elements.append(Paragraph(title, title_style))
    elements.append(Paragraph(f"Total Marks Obtained: {total_obtained}", total_style))
    elements.append(Spacer(1, 6 * mm))

    # Table header
    col_widths = [55 * mm, 25 * mm, 100 * mm]
    header = [
        Paragraph("<b>Question</b>", header_style),
        Paragraph("<b>Marks</b>", header_style),
        Paragraph("<b>Feedback</b>", header_style),
    ]

    table_data = [header]
    for label, marks, total, feedback in items:
        clean_label = deduplicate_label(label)
        marks_str = f"{marks}/{total}"
        fb = wrap_text(feedback, max_len=200)

        row = [
            Paragraph(clean_label, cell_style),
            Paragraph(marks_str, cell_style),
            Paragraph(fb, cell_style),
        ]
        table_data.append(row)

    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                # Header
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                # Body
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
                ("TOPPADDING", (0, 1), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                # Alternating row colors
                *[
                    ("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f8f9fa") if i % 2 == 0 else colors.white)
                    for i in range(1, len(table_data))
                ],
                # Grid
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dee2e6")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )

    elements.append(table)
    doc.build(elements)
    print(f"✓ PDF saved: {output_pdf_path}")


if __name__ == "__main__":
    base = os.path.dirname(os.path.abspath(__file__))

    datasets = [
        {
            "json": os.path.join(base, "grading_results/dataset_15143/grading_final.json"),
            "pdf": os.path.join(base, "grading_results/dataset_15143/grading_report.pdf"),
            "title": "Grading Report — Dataset 15143 (IDT/GST)",
        },
        {
            "json": os.path.join(base, "grading_results/dataset_15099/grading_final.json"),
            "pdf": os.path.join(base, "grading_results/dataset_15099/grading_report.pdf"),
            "title": "Grading Report — Dataset 15099 (Financial Reporting)",
        },
        {
            "json": os.path.join(base, "grading_results/dataset_14865/grading_final.json"),
            "pdf": os.path.join(base, "grading_results/dataset_14865/grading_report.pdf"),
            "title": "Grading Report — Dataset 14865 (Financial Reporting)",
        },
        {
            "json": os.path.join(base, "grading_results/dataset_15151/grading_final.json"),
            "pdf": os.path.join(base, "grading_results/dataset_15151/grading_report.pdf"),
            "title": "Grading Report — Dataset 15151 (Financial Reporting)",
        },
        {
            "json": os.path.join(base, "grading_results/dataset_15112/grading_final.json"),
            "pdf": os.path.join(base, "grading_results/dataset_15112/grading_report.pdf"),
            "title": "Grading Report — Dataset 15112 (IDT/GST)",
        },
    ]

    for ds in datasets:
        print(f"Generating: {ds['title']}")
        generate_pdf(ds["json"], ds["pdf"], ds["title"])

    print("\nDone!")
