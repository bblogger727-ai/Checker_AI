"""
OCR Text to PDF Converter

Combines all page_XX.txt files from each OCR output folder into a single PDF.
"""

import os
import re
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT


def get_sorted_txt_files(folder_path):
    """Get all page_XX.txt files sorted by page number."""
    txt_files = []
    for filename in os.listdir(folder_path):
        if filename.startswith('page_') and filename.endswith('.txt'):
            # Extract page number
            match = re.match(r'page_(\d+)\.txt', filename)
            if match:
                page_num = int(match.group(1))
                txt_files.append((page_num, filename))
    
    # Sort by page number
    txt_files.sort(key=lambda x: x[0])
    return [f[1] for f in txt_files]


def create_pdf_from_ocr_folder(folder_path, output_pdf_path):
    """
    Create a PDF from all page txt files in an OCR output folder.
    
    Args:
        folder_path: Path to the OCR output folder (e.g., ocr_outputs/upload_20260113_132009)
        output_pdf_path: Path for the output PDF
    """
    txt_files = get_sorted_txt_files(folder_path)
    
    if not txt_files:
        print(f"[PDFGenerator] No txt files found in {folder_path}")
        return False
    
    # Create PDF
    doc = SimpleDocTemplate(
        output_pdf_path,
        pagesize=A4,
        rightMargin=0.5*inch,
        leftMargin=0.5*inch,
        topMargin=0.5*inch,
        bottomMargin=0.5*inch
    )
    
    # Styles
    styles = getSampleStyleSheet()
    text_style = ParagraphStyle(
        'OCRText',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        alignment=TA_LEFT,
        spaceAfter=6
    )
    header_style = ParagraphStyle(
        'PageHeader',
        parent=styles['Heading2'],
        fontSize=12,
        spaceAfter=12,
        textColor='#666666'
    )
    
    # Build content
    content = []
    
    for i, txt_file in enumerate(txt_files):
        txt_path = os.path.join(folder_path, txt_file)
        
        # Add page header
        page_num = re.match(r'page_(\d+)\.txt', txt_file).group(1)
        content.append(Paragraph(f"— Page {page_num} —", header_style))
        
        # Read and add text content
        with open(txt_path, 'r', encoding='utf-8') as f:
            text = f.read()
        
        # Split into paragraphs and add
        paragraphs = text.split('\n\n')
        for para in paragraphs:
            if para.strip():
                # Escape special characters for ReportLab
                safe_text = para.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                safe_text = safe_text.replace('\n', '<br/>')
                try:
                    content.append(Paragraph(safe_text, text_style))
                except:
                    # Fallback for problematic text
                    content.append(Paragraph(safe_text[:500] + "...", text_style))
        
        # Add page break between pages (except for last)
        if i < len(txt_files) - 1:
            content.append(PageBreak())
    
    # Build PDF
    doc.build(content)
    print(f"[PDFGenerator] Created: {output_pdf_path}")
    return True


def generate_all_pdfs(ocr_outputs_dir, pdf_output_dir):
    """
    Generate PDFs for all OCR output folders.
    
    Args:
        ocr_outputs_dir: Path to the ocr_outputs directory
        pdf_output_dir: Path to save the generated PDFs
    """
    os.makedirs(pdf_output_dir, exist_ok=True)
    
    # Get all upload folders
    folders = sorted([
        f for f in os.listdir(ocr_outputs_dir)
        if f.startswith('upload_') and os.path.isdir(os.path.join(ocr_outputs_dir, f))
    ])
    
    print(f"[PDFGenerator] Found {len(folders)} OCR output folders")
    
    created = 0
    for folder_name in folders:
        folder_path = os.path.join(ocr_outputs_dir, folder_name)
        output_pdf = os.path.join(pdf_output_dir, f"{folder_name}_ocr.pdf")
        
        if create_pdf_from_ocr_folder(folder_path, output_pdf):
            created += 1
    
    print(f"[PDFGenerator] Created {created} PDFs in {pdf_output_dir}")
    return created


if __name__ == "__main__":
    # Run standalone
    ocr_dir = "ocr_outputs"
    pdf_dir = "ocr_pdfs"
    generate_all_pdfs(ocr_dir, pdf_dir)
