import json
import os
import random
import math
import pytesseract
from pdf2image import convert_from_path
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from pypdf import PdfReader, PdfWriter
import io

# Config
PDF_PATH = "ocr_pdfs/AS 8.pdf"
JSON_PATH = "grading_results/grading_final.json"
OUTPUT_PATH = "grading_results/graded_submission_annotated.pdf"
FONT_PATH = "IndieFlower-Regular.ttf"

def register_font():
    if os.path.exists(FONT_PATH):
        pdfmetrics.registerFont(TTFont('Handwriting', FONT_PATH))
        return 'Handwriting'
    return 'Helvetica'

def scan_pdf_locations(pdf_path, page_dims):
    """
    Scans PDF and returns a map of Question Key -> (PageNum, x, y)
    page_dims: list of (width, height) in PDF points per page.
    """
    print("Scanning PDF for question locations...")
    images = convert_from_path(pdf_path)
    
    locations = {} # Key: (current_section, q_num) -> (page_idx, x, y)
    
    current_section = "SectionA" # Default
    
    for page_idx, img in enumerate(images):
        print(f"Scanning Page {page_idx + 1}...")
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        n_boxes = len(data['text'])
        
        pdf_w, pdf_h = page_dims[page_idx] if page_idx < len(page_dims) else A4
        scale_x = pdf_w / img.width
        scale_y = pdf_h / img.height
        
        for i in range(n_boxes):
            text = data['text'][i].strip()
            conf = int(data['conf'][i])
            if not text or conf < 30: continue
            
            # 1. Section Detection
            if "Section" in text and i+1 < n_boxes:
                next_text = data['text'][i+1].strip()
                if "A" in next_text: current_section = "SectionA"
                if "B" in next_text: current_section = "SectionB"
                
            # 2. Question Detection
            q_num = None
            if text.isdigit() and i+1 < n_boxes and data['text'][i+1].strip() in [")", "."]:
                q_num = text
            elif text.endswith(")") and text[:-1].isdigit():
                q_num = text[:-1]
            elif text.lower().startswith("q") and text[1:].isdigit():
                q_num = text[1:]
                
            if q_num:
                # Tesseract Y is from Top. PDF Y is from Bottom.
                x = data['left'][i] * scale_x
                y_tess = data['top'][i] * scale_y
                y = pdf_h - y_tess 
                
                key = (current_section, q_num)
                if key not in locations:
                    locations[key] = (page_idx, x, y)
                    print(f"Mapped {key} to P{page_idx+1} ({x:.1f}, {y:.1f})")

    return locations

def draw_tick(c, x, y, size=20):
    c.saveState()
    angle = random.uniform(-15, 15)
    scale = random.uniform(0.9, 1.1)
    
    c.translate(x, y)
    c.rotate(angle)
    c.scale(scale, scale)
    
    c.setStrokeColor(colors.red)
    c.setLineWidth(2)
    
    p = c.beginPath()
    p.moveTo(-5, 5) 
    p.lineTo(0, 0)  
    p.lineTo(10, 15)
    c.drawPath(p, stroke=1, fill=0)
    c.restoreState()

def draw_cross(c, x, y, size=20):
    c.saveState()
    angle = random.uniform(-15, 15)
    c.translate(x, y)
    c.rotate(angle)
    c.setStrokeColor(colors.red)
    c.setLineWidth(2)
    
    p = c.beginPath()
    p.moveTo(-8, -8)
    p.lineTo(8, 8)
    p.moveTo(-8, 8)
    p.lineTo(8, -8)
    c.drawPath(p, stroke=1, fill=0)
    c.restoreState()

def annotate_pdf(pdf_path=PDF_PATH, json_path=JSON_PATH, output_path=OUTPUT_PATH):
    # 1. Load Data & Dims
    grading_data = {}
    if os.path.exists(json_path):
        with open(json_path, 'r') as f:
            grading_data = json.load(f).get("graded_answers", {})

    reader = PdfReader(pdf_path)
    num_pages = len(reader.pages)
    
    page_dims = []
    for p in reader.pages:
        # mediabox usually [0, 0, w, h]
        w = float(p.mediabox.width)
        h = float(p.mediabox.height)
        page_dims.append((w, h))

    locations = scan_pdf_locations(pdf_path, page_dims)
    
    font_name = register_font()
    
    # 2. Create Overlay
    packet = io.BytesIO()
    c = canvas.Canvas(packet)
    
    for page_idx in range(num_pages):
        width, height = page_dims[page_idx]
        c.setPageSize((width, height))
        
        c.setFont(font_name, 16)
        c.setFillColor(colors.red)
        
        # Iterate Grading Data
        for section, sec_data in grading_data.items():
            for q_group, q_content in sec_data.items():
                
                # Determine Q Number
                items_to_grade = []
                if q_group == "MCQ":
                    for sub_id, item in q_content.items():
                        items_to_grade.append((sub_id, item))
                else:
                    # Q1. Use q_group number.
                    q_num = q_group.replace("Q", "")
                    # If multiple subparts (a, b), place marks at same Q location but offset?
                    # Or check if "a)" exists location?
                    # Currently we only mapped Q nums.
                    # Let's stack marks if multiple parts.
                    
                    # We only mapped "1", "2". We didn't map "a".
                    # So place all marks for Q1 near Q1 location, stacked vertically?
                    
                    subparts = list(q_content.items())
                    for idx, (sub_id, item) in enumerate(subparts):
                        items_to_grade.append((q_num, item, idx)) # Add Index for stacking

                for entry in items_to_grade:
                     if len(entry) == 3:
                         q_num, item, stack_idx = entry
                     else:
                         q_num, item = entry
                         stack_idx = 0
                     
                     loc_key = (section, q_num)
                     
                     if loc_key not in locations:
                         # Fallback: Try just q_num 
                         # (Maybe Section wasn't detected?)
                         if ("SectionA", q_num) in locations:
                             loc_key = ("SectionA", q_num)
                         elif ("SectionB", q_num) in locations:
                             loc_key = ("SectionB", q_num)
                         else: 
                             continue
                     
                     loc_page, lx, ly = locations[loc_key]
                     
                     if loc_page != page_idx: continue
                     
                     # Extract marks
                     marks = item.get("marks_obtained", 0)
                     total = item.get("marks_total", 0)
                     is_full = (marks == total and total > 0)
                     is_zero = (marks == 0)
                     
                     draw_x = lx - 50
                     draw_y = ly - (stack_idx * 30) # Stack downwards
                     
                     # Jitter
                     draw_x += random.uniform(-2, 2)
                     draw_y += random.uniform(-2, 2)
                     
                     # Draw Symbol
                     if is_zero:
                         draw_cross(c, draw_x, draw_y)
                     else:
                         draw_tick(c, draw_x, draw_y)
                     
                     # Draw Score
                     score_text = f"+{marks}" if marks > 0 else "0"
                     c.drawString(draw_x - 30, draw_y, score_text)
        
        c.showPage()
        
    c.save()
    packet.seek(0)
    overlay_pdf = PdfReader(packet)
    
    # 3. Merge
    print("Merging annotations...")
    output = PdfWriter()
    
    for i in range(num_pages):
        original_page = reader.pages[i]
        if i < len(overlay_pdf.pages):
           original_page.merge_page(overlay_pdf.pages[i])
        output.add_page(original_page)
        
    with open(output_path, "wb") as f:
        output.write(f)
        
    print(f"Saved annotated PDF to {output_path}")

if __name__ == "__main__":
    annotate_pdf()
