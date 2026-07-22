#!/usr/bin/env python3
"""
CA Single-Question Feedback Pipeline

Usage:
    python3 run_ca_single_question.py \
        --question-image /path/to/question.jpg \
        --model-answer-image /path/to/model_answer.jpg \
        --student-answer-image /path/to/student_answer.jpg \
        --marks-total 6 \
        --marks-scored 4 \
        --dataset MY_DATASET

This pipeline:
1. OCRs the question + model answer images via OpenAI GPT-4o-mini (cheap)
2. OCRs the student answer image via Claude (better for handwriting)
3. Builds a minimal single-question schema
4. Generates detailed feedback using the existing CA feedback generator
5. Saves: feedback_final.json, ca_feedback_report.md, ca_feedback_report.pdf
"""

import os
import sys
import json
import argparse

# Ensure imports work from the backend root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from claude_grading.single_question_ocr import ocr_question_and_model_answer, ocr_student_answer
from claude_grading.ca_feedback_generator import generate_ca_feedback


def generate_pdf(report_md: str, pdf_path: str):
    """Convert markdown report to PDF."""
    try:
        import markdown
        from fpdf import FPDF

        class PDF(FPDF):
            def header(self):
                self.set_font('helvetica', 'B', 15)
                self.cell(0, 10, 'CA Student Feedback Report', new_x='LMARGIN', new_y='NEXT', align='C')
                self.ln(3)
            def footer(self):
                self.set_y(-15)
                self.set_font('helvetica', 'I', 8)
                self.cell(0, 10, f'Page {self.page_no()}', align='C')

        # Clean unicode chars that can't be encoded by standard PDF fonts
        safe_md = report_md.replace('₹', 'Rs.').replace('✓', '[OK]').replace('✗', '[X]')
        safe_md = safe_md.encode('latin-1', 'replace').decode('latin-1')
        html = markdown.markdown(safe_md)
        html = html.replace('<strong>', '<b>').replace('</strong>', '</b>')
        html = html.replace('<em>', '<i>').replace('</em>', '</i>')

        pdf = PDF()
        pdf.add_page()
        pdf.set_font("helvetica", size=11)
        try:
            pdf.write_html(html)
        except Exception:
            # Fallback to plain text if HTML rendering fails
            pdf.multi_cell(0, 6, safe_md)
        pdf.output(pdf_path)
        print(f"✓ PDF saved to: {pdf_path}")
    except ImportError:
        print("⚠️  fpdf2/markdown not installed. Skipping PDF generation. Run: pip install fpdf2 markdown")


def main():
    parser = argparse.ArgumentParser(description='CA Single-Question Feedback Pipeline')
    parser.add_argument('--question-image', required=True, help='Path to question image file')
    parser.add_argument('--model-answer-image', required=True, help='Path to model answer image file')
    parser.add_argument('--student-answer-image', required=True, nargs='+', help='Path to student answer image file(s)')
    parser.add_argument('--marks-total', required=True, type=float, help='Total marks allotted to this question')
    parser.add_argument('--marks-scored', required=True, type=float, help='Marks scored by the student')
    parser.add_argument('--dataset', required=True, help='Dataset ID (used for output directory naming)')
    args = parser.parse_args()

    # Validate input files exist
    paths_to_check = [
        ("Question image", args.question_image),
        ("Model answer image", args.model_answer_image),
    ]
    for sa_img in args.student_answer_image:
        paths_to_check.append(("Student answer image", sa_img))

    for label, path in paths_to_check:
        if not os.path.exists(path):
            print(f"Error: {label} not found at: {path}")
            sys.exit(1)

    # Prepare output directory
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dataset_dir = os.path.join(base_dir, "feedback_results", f"dataset_{args.dataset}")
    os.makedirs(dataset_dir, exist_ok=True)

    print("=" * 60)
    print("CA SINGLE-QUESTION FEEDBACK PIPELINE")
    print("=" * 60)
    print(f"Question  : {args.question_image}")
    print(f"Model Ans : {args.model_answer_image}")
    print(f"Student   : {', '.join(args.student_answer_image)}")
    print(f"Marks     : {args.marks_scored} / {args.marks_total}")
    print()

    # ── Step 1: OCR question and model answer (OpenAI GPT-4o-mini) ──────
    print("[Step 1] OCR: Question + Model Answer (OpenAI GPT-4o-mini)...")
    qma = ocr_question_and_model_answer(args.question_image, args.model_answer_image)
    question_text = qma.get("question_text", "").strip()
    model_answer = qma.get("model_answer", "").strip()

    if not question_text:
        print("⚠️  Warning: No question text extracted. Proceeding with empty string.")
    if not model_answer:
        print("⚠️  Warning: No model answer extracted. Proceeding with empty string.")

    # ── Step 2: OCR student answer (Claude) ─────────────────────────────
    print("\n[Step 2] OCR: Student Answer (Claude)...")
    student_answer = ocr_student_answer(args.student_answer_image)

    if not student_answer:
        print("⚠️  Warning: No student answer extracted. Proceeding with empty string.")

    # ── Step 3: Build minimal schema & generate feedback ─────────────────
    print("\n[Step 3] Generating detailed feedback...")
    feedback = generate_ca_feedback(
        question_text=question_text,
        model_answer=model_answer,
        student_answer=student_answer,
        marks_total=args.marks_total,
        marks_scored=args.marks_scored,
    )

    # ── Step 4: Build result JSON ─────────────────────────────────────────
    result = {
        "question_id": "SQ-1",
        "question_text": question_text,
        "model_answer": model_answer,
        "student_answer": student_answer,
        "marks": args.marks_total,
        "marks_scored": args.marks_scored,
        "feedback": feedback,
    }

    # Save feedback JSON
    feedback_path = os.path.join(dataset_dir, "feedback_final.json")
    with open(feedback_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"✓ Feedback JSON saved to: {feedback_path}")

    # ── Step 5: Generate Markdown Report ─────────────────────────────────
    fb = feedback
    report_md = f"""# CA Student Feedback Report - Single Question

## Question
{question_text}

---

## Marks: {args.marks_scored} / {args.marks_total}

---

## What Went Right
{fb.get('what_went_right', 'N/A')}

---

## What Went Wrong
{fb.get('what_went_wrong', 'N/A')}

---

## Conclusion
{fb.get('conclusion', 'N/A')}
"""

    report_path = os.path.join(dataset_dir, "ca_feedback_report.md")
    with open(report_path, "w") as f:
        f.write(report_md)
    print(f"✓ Markdown report saved to: {report_path}")

    # ── Step 6: Generate PDF ──────────────────────────────────────────────
    pdf_path = os.path.join(dataset_dir, "ca_feedback_report.pdf")
    generate_pdf(report_md, pdf_path)

    print("\n" + "=" * 60)
    print("SINGLE-QUESTION FEEDBACK PIPELINE COMPLETED")
    print("=" * 60)
    print(f"Outputs in: {dataset_dir}")


if __name__ == "__main__":
    main()
