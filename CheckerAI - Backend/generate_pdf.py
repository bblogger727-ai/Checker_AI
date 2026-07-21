from fpdf import FPDF
import markdown
import os
import sys

class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 15)
        self.cell(0, 10, 'CA Student Feedback Report', 0, 1, 'C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

def convert_md_to_pdf(md_path, pdf_path):
    if not os.path.exists(md_path):
        print(f"Error: {md_path} not found.")
        return

    with open(md_path, 'r') as f:
        md_text = f.read()

    # Robust Unicode Cleaning for FPDF standard fonts
    md_text = md_text.replace('₹', 'Rs.')
    md_text = md_text.replace('✓', '[OK]')
    # Strip other non-latin-1 characters
    md_text = md_text.encode('latin-1', 'replace').decode('latin-1')

    # Convert MD to HTML (fpdf2 basic html support)
    # fpdf2 supports: b, i, u, a, p, br, h1-h6, font, center
    html = markdown.markdown(md_text)
    
    # Custom cleaning for fpdf2 html parser
    # markdown-it or similar might be better but let's try simple replacement
    html = html.replace('<strong>', '<b>').replace('</strong>', '</b>')
    html = html.replace('<em>', '<i>').replace('</em>', '</i>')
    
    pdf = PDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    
    try:
        pdf.write_html(html)
        pdf.output(pdf_path)
        print(f"✓ PDF saved to: {pdf_path}")
    except Exception as e:
        print(f"Error during PDF generation: {e}")
        # Fallback to simple text if HTML fails
        pdf = PDF()
        pdf.add_page()
        pdf.set_font("Arial", size=10)
        pdf.multi_cell(0, 5, md_text)
        pdf.output(pdf_path)
        print(f"✓ PDF saved (text-only fallback) to: {pdf_path}")

if __name__ == "__main__":
    dataset_id = "DMCI_TEST"
    base = "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results"
    md_p = f"{base}/dataset_{dataset_id}/ca_feedback_report.md"
    pdf_p = f"{base}/dataset_{dataset_id}/ca_feedback_report.pdf"
    convert_md_to_pdf(md_p, pdf_p)
