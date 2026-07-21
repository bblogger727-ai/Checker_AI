import os
import sys

# Generate markdown using existing script
os.system("python3 run_ca_report_6.py --dataset FR_Manual_Run")

# Import the PDF generator routine
from generate_pdf import convert_md_to_pdf

base = "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results/dataset_FR_Manual_Run"
md_p = f"{base}/ca_feedback_report.md"
pdf_p = f"{base}/ca_feedback_report.pdf"

print("Converting newly generated MD to PDF...")
convert_md_to_pdf(md_p, pdf_p)
print("Finished!")
