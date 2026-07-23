import os
import sys
import subprocess

def main():
    print("==========================================================")
    print("  Regenerate Checked Copy (Post-Crash Recovery)")
    print("==========================================================")
    
    dataset_name = input("Enter the dataset folder name (e.g., dataset_15942): ").strip()
    pdf_path = input("Enter the path to the original student answer sheet PDF: ").strip()
    
    if not dataset_name or not pdf_path:
        print("Dataset name and PDF path are required. Exiting.")
        return
        
    base_dir = os.path.join("grading_results", dataset_name)
    grading_json = os.path.join(base_dir, "grading_final.json")
    aligned_json = os.path.join(base_dir, "aligned_answers.json")
    ocr_txt = os.path.join(base_dir, "ocr_output.txt")
    output_pdf = os.path.join(base_dir, "checked_copy.pdf")
    
    if not os.path.exists(grading_json):
        print(f"Error: Could not find {grading_json}")
        return
        
    cmd = [
        "python3", "generate_checked_copy_v2.py",
        "--pdf", pdf_path,
        "--grading", grading_json,
        "--aligned", aligned_json,
        "--output", output_pdf
    ]
    
    if os.path.exists(ocr_txt):
        cmd.extend(["--ocr", ocr_txt])
        
    print(f"\nRunning command:\n{' '.join(cmd)}\n")
    
    try:
        subprocess.run(cmd, check=True)
        print(f"\nSuccess! The checked copy has been generated at: {output_pdf}")
    except subprocess.CalledProcessError as e:
        print(f"\nError: Generation failed with exit code {e.returncode}")

if __name__ == "__main__":
    main()
