import json
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

def generate_pdf(json_path, output_path):
    print(f"Loading JSON from: {json_path}")
    with open(json_path, 'r') as f:
        data = json.load(f)

    doc = SimpleDocTemplate(output_path, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    
    # Custom Styles
    styles.add(ParagraphStyle(name='QuestionHeader', parent=styles['Heading3'], fontSize=11, spaceAfter=4, textColor=colors.darkblue))
    styles.add(ParagraphStyle(name='CellText', parent=styles['BodyText'], fontSize=9, leading=11))
    styles.add(ParagraphStyle(name='FeedbackText', parent=styles['BodyText'], fontSize=9, leading=11, textColor=colors.darkslategrey))
    styles.add(ParagraphStyle(name='MarksText', parent=styles['BodyText'], fontName='Helvetica-Bold', fontSize=10, alignment=1)) # Center aligned
    styles.add(ParagraphStyle(name='KeyPointGood', parent=styles['BodyText'], fontSize=8, textColor=colors.green, leading=10))
    styles.add(ParagraphStyle(name='KeyPointBad', parent=styles['BodyText'], fontSize=8, textColor=colors.red, leading=10))

    story = []

    # Title
    story.append(Paragraph("CheckerAI Grading Report", styles['Title']))
    
    # Metadata Table
    meta = data.get("metadata", {})
    meta_data = [
        ["Graded At", meta.get('graded_at', '-')],
        ["Total Score", f"{meta.get('total_marks_obtained', 0)} / {meta.get('total_marks_possible', 0)}"],
        ["Percentage", f"{meta.get('percentage', 0)}%"],
        ["Grade", meta.get('grade', '-')]
    ]
    
    meta_table = Table(meta_data, colWidths=[1.5*inch, 4*inch])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,-1), colors.lightgrey),
        ('TEXTCOLOR', (0,0), (0,-1), colors.black),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 20))

    graded_answers = data.get("graded_answers", {})
    sorted_sections = sorted(graded_answers.keys())
    
    for section_name in sorted_sections:
        story.append(Paragraph(f"Section: {section_name}", styles['Heading2']))
        story.append(Spacer(1, 10))
        section_data = graded_answers[section_name]
        
        # Sort Questions
        def sort_key(k):
            if k == "MCQ": return (0, 0)
            if k.startswith("Q") and k[1:].isdigit(): return (1, int(k[1:]))
            return (2, k)
            
        sorted_qs = sorted(section_data.keys(), key=sort_key)

        # Create Table Data Header
        # Columns: Question | Evaluation & Feedback | Marks
        table_data = [
            [Paragraph("<b>Q. No</b>", styles['CellText']), 
             Paragraph("<b>Evaluation & Feedback</b>", styles['CellText']), 
             Paragraph("<b>Marks</b>", styles['CellText'])]
        ]

        for q_key in sorted_qs:
            q_data_root = section_data[q_key]
            
            # Determine if this is a Flat Question (data directly here) or Nested (container)
            items_to_process = []
            
            def collect_graded_items(data, label_prefix):
                """Recursively collect graded items, handling any depth of nesting."""
                if not isinstance(data, dict):
                    return
                # If this dict has grading keys, it's a leaf graded item
                if "marks_obtained" in data or "student_answer" in data or "feedback" in data:
                    items_to_process.append((label_prefix, data))
                    return
                # Otherwise, recurse into subparts
                for sub_key in sorted(data.keys()):
                    sub_item = data[sub_key]
                    if isinstance(sub_item, dict):
                        # Build a readable label
                        if sub_key == label_prefix or sub_key == q_key:
                            new_label = label_prefix
                        else:
                            new_label = f"{label_prefix}-{sub_key}"
                        collect_graded_items(sub_item, new_label)
            
            collect_graded_items(q_data_root, q_key)

            for sub_key, item in items_to_process:
                # Question Number Cell
                q_label = q_key
                is_mcq = "MCQ" in section_name or "MCQ" in q_key or "MCQ" in str(item.get("question_id", ""))
                
                if is_mcq:
                    # Clean MCQ numbering: "MCQ 1", "MCQ 2", etc.
                    if sub_key.isdigit():
                        q_label = f"MCQ {sub_key}"
                    else:
                        num_part = ''.join(filter(str.isdigit, sub_key))
                        q_label = f"MCQ {num_part}" if num_part else sub_key
                else:
                    if sub_key != q_key:
                        q_label = f"{q_key}-{sub_key}"

                # Evaluation Cell
                eval_content = []
                
                # Feedback
                feed = item.get("feedback", "")
                if feed:
                    eval_content.append(Paragraph(f"<b>Feedback:</b> {feed}", styles['FeedbackText']))
                    eval_content.append(Spacer(1, 4))
                
                # Key Points
                kpc = item.get("correct_items", item.get("key_points_covered", []))
                if kpc:
                    eval_content.append(Paragraph("<b>✅ Strengths:</b>", styles['CellText']))
                    for kp in kpc: eval_content.append(Paragraph(f"• {kp}", styles['KeyPointGood']))
                
                kpm = item.get("major_errors", item.get("key_points_missed", []))
                if kpm:
                    eval_content.append(Spacer(1, 4))
                    eval_content.append(Paragraph("<b>❌ Weaknesses:</b>", styles['CellText']))
                    for kp in kpm: eval_content.append(Paragraph(f"• {kp}", styles['KeyPointBad']))
                
                # Marks Cell
                m_obt = item.get("marks_obtained", 0)
                m_tot = item.get("marks_total", 0)
                marks_str = f"{m_obt} / {m_tot}"
                
                table_data.append([
                    Paragraph(str(q_label), styles['CellText']),
                    eval_content,
                    Paragraph(marks_str, styles['MarksText'])
                ])

        # Configure Table Style
        # Col Widths: Q=1.0, Eval=5.3, Marks=0.8 (Total ~7.1 inch)
        t = Table(table_data, colWidths=[1.0*inch, 5.3*inch, 0.8*inch], repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.navy),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('ALIGN', (-1,0), (-1,-1), 'CENTER'), # Center align marks column
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.white]),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ]))
        
        story.append(t)
        story.append(Spacer(1, 20))
        story.append(PageBreak())

    print(f"Building PDF at {output_path}...")
    doc.build(story)
    print("Done.")

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(base_dir, "grading_results/grading_final.json")
    pdf_path = os.path.join(base_dir, "grading_results/grading_report.pdf")
    
    if not os.path.exists(json_path):
        # Fallback for different CWD
        json_path = "CheckerAI - Backend/grading_results/grading_final.json"
        pdf_path = "CheckerAI - Backend/grading_results/grading_report.pdf"
        
    if os.path.exists(json_path):    
        generate_pdf(json_path, pdf_path)
    else:
        print("Could not find json file.")
