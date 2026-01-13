"""
PDF Generator Service

Converts grading results JSON to formatted PDF report.
"""

import os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib import colors


def generate_grading_pdf(student_name: str, exam_name: str, grading_json: dict, output_dir: str) -> str:
    """
    Generate a formatted PDF from grading results.
    
    Args:
        student_name: Name of the student
        exam_name: Name of the exam
        grading_json: Full grading results dict
        output_dir: Directory to save the PDF
    
    Returns:
        Path to the generated PDF
    """
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = student_name.replace(" ", "_").replace("/", "_")
    pdf_path = os.path.join(output_dir, f"{safe_name}_{timestamp}_result.pdf")
    
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        rightMargin=0.75*inch,
        leftMargin=0.75*inch,
        topMargin=0.5*inch,
        bottomMargin=0.5*inch
    )
    
    # Styles
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=HexColor('#1a365d'),
        spaceAfter=12
    )
    
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=12,
        textColor=HexColor('#4a5568'),
        spaceAfter=6
    )
    
    section_style = ParagraphStyle(
        'Section',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=HexColor('#2d3748'),
        spaceBefore=16,
        spaceAfter=8
    )
    
    question_style = ParagraphStyle(
        'Question',
        parent=styles['Normal'],
        fontSize=10,
        textColor=HexColor('#2d3748'),
        spaceBefore=8,
        spaceAfter=4
    )
    
    feedback_style = ParagraphStyle(
        'Feedback',
        parent=styles['Normal'],
        fontSize=9,
        textColor=HexColor('#718096'),
        leftIndent=20,
        spaceAfter=8
    )
    
    # Build content
    content = []
    
    # Header
    content.append(Paragraph("Exam Evaluation Report", title_style))
    content.append(Paragraph(f"<b>Student:</b> {student_name}", subtitle_style))
    content.append(Paragraph(f"<b>Exam:</b> {exam_name}", subtitle_style))
    content.append(Paragraph(f"<b>Date:</b> {datetime.now().strftime('%d %B %Y')}", subtitle_style))
    content.append(Spacer(1, 12))
    
    # Summary table
    metadata = grading_json.get("metadata", {})
    summary_data = [
        ["Total Marks", f"{metadata.get('total_marks_obtained', 0)} / {metadata.get('total_marks_possible', 0)}"],
        ["Percentage", f"{metadata.get('percentage', 0):.1f}%"],
        ["Grade", metadata.get('grade', '-')],
        ["Questions Attempted", f"{metadata.get('total_questions', 0)}"],
    ]
    
    summary_table = Table(summary_data, colWidths=[2*inch, 2*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), HexColor('#e2e8f0')),
        ('TEXTCOLOR', (0, 0), (-1, -1), HexColor('#2d3748')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#cbd5e0')),
    ]))
    content.append(summary_table)
    content.append(Spacer(1, 20))
    
    # Divider
    content.append(HRFlowable(width="100%", thickness=1, color=HexColor('#e2e8f0')))
    content.append(Spacer(1, 12))
    
    # Detailed results
    content.append(Paragraph("Detailed Results", section_style))
    
    graded_answers = grading_json.get("graded_answers", {})
    
    for section_key, section_content in graded_answers.items():
        content.append(Paragraph(f"<b>{section_key}</b>", section_style))
        
        add_questions_to_content(content, section_content, question_style, feedback_style, "")
    
    # Build PDF
    doc.build(content)
    
    return pdf_path


def add_questions_to_content(content, data, question_style, feedback_style, prefix):
    """Recursively add questions to PDF content."""
    
    if isinstance(data, dict):
        # Check if this is a leaf question (has marks_obtained)
        if "marks_obtained" in data:
            q_num = prefix if prefix else "Question"
            marks = f"{data.get('marks_obtained', 0)}/{data.get('marks_total', 0)}"
            
            # Question line
            question_text = data.get('question', '')[:100] + "..." if len(data.get('question', '')) > 100 else data.get('question', '')
            content.append(Paragraph(f"<b>{q_num}</b>: {question_text}", question_style))
            
            # Marks
            content.append(Paragraph(f"<b>Marks:</b> {marks}", feedback_style))
            
            # Feedback
            feedback = data.get('feedback', '')
            if feedback:
                safe_feedback = feedback.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                content.append(Paragraph(f"<b>Feedback:</b> {safe_feedback}", feedback_style))
            
            return
        
        # Otherwise recurse into nested structure
        for key, value in data.items():
            if key in ['question', 'student_answer', 'model_answer']:
                continue
            new_prefix = f"{prefix}-{key}" if prefix else key
            add_questions_to_content(content, value, question_style, feedback_style, new_prefix)
