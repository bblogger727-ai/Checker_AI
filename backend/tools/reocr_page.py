"""
Re-OCR a single page from a PDF
"""

from pdf2image import convert_from_path
from app.services.ocr_service import perform_ocr
import sys


def reocr_page(pdf_path: str, page_number: int, output_path: str):
    """
    Re-OCR a specific page from a PDF.
    
    Args:
        pdf_path: Path to the source PDF
        page_number: Page number to OCR (1-indexed)
        output_path: Path to save the OCR text
    """
    print(f"[ReOCR] Converting page {page_number} from {pdf_path}...")
    
    # Convert just that page
    images = convert_from_path(pdf_path, first_page=page_number, last_page=page_number)
    
    if not images:
        print(f"[ReOCR] ERROR: Could not extract page {page_number}")
        return False
    
    print(f"[ReOCR] Running OCR...")
    text = perform_ocr(images[0])
    
    print(f"[ReOCR] Saving to {output_path}...")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(text)
    
    print(f"[ReOCR] Done! Extracted {len(text)} characters")
    return True


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python reocr_page.py <pdf_path> <page_number> <output_path>")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    page_number = int(sys.argv[2])
    output_path = sys.argv[3]
    
    reocr_page(pdf_path, page_number, output_path)
