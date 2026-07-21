#!/usr/bin/env python3
"""
Stage 6: PDF Report Generation (Simplified)
Generates a clean, tabular PDF report with all questions
"""

import json
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
import sys
from pathlib import Path

def create_simplified_report(grading_json_path, output_pdf_path):
    """Create a simplified tabular PDF report from grading JSON"""
    
    # Load grading results
    print(f"Loading JSON from: {grading_json_path}")
    with open(grading_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    metadata = data.get('metadata', {})
    graded_answers = data.get('graded_answers', {})
    
    # Create PDF
    print(f"Building PDF at {output_pdf_path}...")
    doc = SimpleDocTemplate(output_pdf_path, pagesize=A4,
                            rightMargin=30, leftMargin=30,
                            topMargin=30, bottomMargin=30)
    
    elements = []
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#1a237e'),
        spaceAfter=30,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    header_style = ParagraphStyle(
        'CustomHeader',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#333333'),
        alignment=TA_LEFT,
        fontName='Helvetica-Bold'
    )
    
    # Title
    elements.append(Paragraph("CA Exam Grading Report", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    # Summary header
    summary_data = [
        ['Total Score:', f"{metadata.get('total_marks_obtained', 0)}/{metadata.get('total_marks_possible', 0)}"],
        ['Percentage:', f"{metadata.get('percentage', 0)}%"],
        ['Grade:', metadata.get('grade', 'N/A')],
        ['Questions Attempted:', f"{metadata.get('total_questions', 0) - sum(1 for sec in graded_answers.values() for q, qdata in sec.items() if q != 'MCQ' and isinstance(qdata, dict) and qdata.get('student_answer', '').strip() == '')} / {metadata.get('total_questions', 0)}"]
    ]
    
    summary_table = Table(summary_data, colWidths=[2*inch, 3*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#e3f2fd')),
        ('BACKGROUND', (1, 0), (1, -1), colors.white),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    
    elements.append(summary_table)
    elements.append(Spacer(1, 0.4*inch))
    
    # Question-wise breakdown header
    elements.append(Paragraph("Question-Wise Breakdown", header_style))
    elements.append(Spacer(1, 0.2*inch))
    
    # Prepare question data
    question_rows = [['Q. No.', 'Marks', 'Feedback']]
    
    # Collect all questions
    all_questions = []
    for section_key, section_content in graded_answers.items():
        for question_key, question_data in section_content.items():
            if question_key == 'MCQ':
                continue
            
            # Handle nested structure (Q1 -> Q1 -> {...})
            if isinstance(question_data, dict) and question_key in question_data:
                # Check if nested dict has content or use outer dict
                if question_data[question_key] and isinstance(question_data[question_key], dict):
                    # Use nested for marks/feedback
                    q_data = question_data[question_key]
                    # But check outer dict for student_answer (Q2, Q5, Q6 have it there)
                    student_answer = question_data.get('student_answer', q_data.get('student_answer', ''))
                else:
                    # Use outer dict
                    q_data = question_data
                    student_answer = question_data.get('student_answer', '')
            else:
                q_data = question_data
                student_answer = question_data.get('student_answer', '') if isinstance(question_data, dict) else ''
            
            if isinstance(q_data, dict):
                q_num = question_key
                marks_obtained = q_data.get('marks_obtained', 0)
                marks_total = q_data.get('marks_total', 0)
                feedback = q_data.get('feedback', 'No feedback available')
                
                # Truncate feedback if too long
                if len(feedback) > 250:
                    feedback = feedback[:247] + "..."
                
                # Mark unattempted questions - check actual student_answer content
                if not student_answer or str(student_answer).strip() == '':
                    feedback = "Question not attempted"
                
                all_questions.append((q_num, marks_obtained, marks_total, feedback))
    
    # Sort questions (Q1, Q2, ...)
    all_questions.sort(key=lambda x: int(x[0].replace('Q', '')))
    
    # Build table rows
    for q_num, marks_obtained, marks_total, feedback in all_questions:
        marks_str = f"{marks_obtained}/{marks_total}"
        
        # Wrap feedback text
        feedback_para = Paragraph(feedback, ParagraphStyle(
            'FeedbackText',
            parent=styles['Normal'],
            fontSize=9,
            leading=11,
            alignment=TA_LEFT
        ))
        
        question_rows.append([
            q_num,
            marks_str,
            feedback_para
        ])
    
    # Create questions table
    questions_table = Table(question_rows, colWidths=[0.8*inch, 1*inch, 4.5*inch])
    questions_table.setStyle(TableStyle([
        # Header row
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a237e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        
        # Data rows
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # Q. No. center
        ('ALIGN', (1, 1), (1, -1), 'CENTER'),  # Marks center
        ('ALIGN', (2, 1), (2, -1), 'LEFT'),    # Feedback left
        ('FONTNAME', (0, 1), (1, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 1), (2, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        
        # Alternate row colors
        *[('BACKGROUND', (0, i), (-1, i), colors.HexColor('#f5f5f5')) for i in range(2, len(question_rows), 2)]
    ]))
    
    elements.append(questions_table)
    
    # Build PDF
    doc.build(elements)
    print("Done.")

if __name__ == "__main__":
    print("=" * 60)
    print("STAGE 6: Simplified Report Generation")
    print("=" * 60)
    
    grading_results_path = "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results/grading_final.json"
    output_pdf = "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results/Simplified_Report.pdf"
    
    # Check if grading results exist
    if not Path(grading_results_path).exists():
        print(f"❌ Missing: {grading_results_path}")
        print("   Run: python3 run_stage_5_grading.py")
        sys.exit(1)
    
    print(f"Grading results: {grading_results_path}")
    create_simplified_report(grading_results_path, output_pdf)
    
    print(f"✓ Report saved to: {output_pdf}")
    print("")
    print("✓ Simplified report complete!")
