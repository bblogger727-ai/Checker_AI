#!/usr/bin/env python3
"""
CA Specialized Stage 7:
Generates a professional PDF report from the feedback results.
"""
import os
import sys
import json
import argparse
import re
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

def sort_key(q):
    qid = q.get("question_id") or q.get("question_number", "Z99")
    match = re.search(r'(\d+)', str(qid))
    num = int(match.group(1)) if match else 999
    return (num, str(qid))

def generate_ca_pdf(feedback_results, output_path, title="Feedback Report"):
    doc = SimpleDocTemplate(
        output_path, 
        pagesize=A4, 
        rightMargin=20*mm, 
        leftMargin=20*mm, 
        topMargin=20*mm, 
        bottomMargin=20*mm
    )
    
    styles = getSampleStyleSheet()
    
    # Custom Styles
    title_style = ParagraphStyle(
        'ReportTitle',
        parent=styles['Heading1'],
        fontSize=20,
        spaceAfter=12,
        alignment=1, # Center
        textColor=colors.HexColor("#2c3e50")
    )
    
    section_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading2'],
        fontSize=14,
        spaceBefore=12,
        spaceAfter=6,
        textColor=colors.HexColor("#2980b9"),
        borderPadding=2,
        borderColor=colors.HexColor("#bdc3c7"),
        borderWidth=0
    )
    
    sub_section_style = ParagraphStyle(
        'SubSectionHeader',
        parent=styles['Heading3'],
        fontSize=11,
        spaceBefore=8,
        spaceAfter=4,
        textColor=colors.HexColor("#2c3e50")
    )
    
    body_style = ParagraphStyle(
        'BodyText',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        spaceAfter=6,
        alignment=4 # Justified
    )
    
    marks_style = ParagraphStyle(
        'MarksText',
        parent=styles['Normal'],
        fontSize=11,
        fontName='Helvetica-Bold',
        textColor=colors.HexColor("#7f8c8d"),
        spaceAfter=10
    )

    story = []
    
    # Title
    story.append(Paragraph(title, title_style))
    story.append(Spacer(1, 10*mm))
    
    # Collect and Sort Questions
    def _collect_questions(node, questions=None):
        if questions is None: questions = []
        if isinstance(node, dict):
            if "feedback" in node:
                questions.append(node)
            else:
                for v in node.values():
                    _collect_questions(v, questions)
        elif isinstance(node, list):
            for item in node:
                _collect_questions(item, questions)
        return questions

    all_questions = _collect_questions(feedback_results)
    all_questions.sort(key=sort_key)
    
    # Summary Table Removed as per user request

    # Detailed Feedback
    for q in all_questions:
        qid = q.get("question_id") or q.get("question_number", "Unknown")
        label = str(qid).split('-')[-1]
        if not label.startswith('Q'): label = f"Q{label}"
        
        ms = q.get("marks_scored", "?")
        mt = q.get("marks", "?")
        
        story.append(Paragraph(f"Question {label}", section_style))
        story.append(Paragraph(f"Marks Scored: {ms} / {mt}", marks_style))
        
        fb = q["feedback"]
        
        sections = [
            ("What Went Right", "what_went_right", colors.HexColor("#27ae60")),
            ("What Went Wrong", "what_went_wrong", colors.HexColor("#c0392b")),
            ("Conclusion", "conclusion", colors.HexColor("#2c3e50"))
        ]
        
        for name, key, color in sections:
            content = fb.get(key, "").strip()
            if content and content.lower() != "n/a":
                # Header with color
                h_style = ParagraphStyle(
                    f'H_{key}',
                    parent=sub_section_style,
                    textColor=color
                )
                story.append(Paragraph(name, h_style))
                story.append(Paragraph(content, body_style))
                story.append(Spacer(1, 2*mm))
        
        story.append(Spacer(1, 5*mm))
        # Horizontal line equivalent using table
        line = Table([[""]], colWidths=[170*mm], rowHeights=[0.2*mm])
        line.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#bdc3c7"))]))
        story.append(line)
        story.append(Spacer(1, 10*mm))

    doc.build(story)
    print(f"✓ PDF report saved to: {output_path}")

def main():
    parser = argparse.ArgumentParser(description='CA Specialized PDF Report Generation')
    parser.add_argument('--dataset', required=True, help='Dataset ID')
    parser.add_argument('--title', default='Audit Feedback Report', help='Report Title')
    
    args = parser.parse_args()
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dataset_dir = os.path.join(base_dir, "feedback_results", f"dataset_{args.dataset}")
    
    feedback_path = os.path.join(dataset_dir, "feedback_final.json")
    
    if not os.path.exists(feedback_path):
        print(f"Error: Feedback results not found at {feedback_path}")
        sys.exit(1)
        
    with open(feedback_path, "r") as f:
        feedback_results = json.load(f)
    
    output_path = os.path.join(dataset_dir, "ca_feedback_report.pdf")
    
    print("="*60)
    print("CA STAGE 7: Specialized PDF Report Generation")
    print("="*60)
    
    generate_ca_pdf(feedback_results, output_path, title=args.title)

if __name__ == "__main__":
    main()
