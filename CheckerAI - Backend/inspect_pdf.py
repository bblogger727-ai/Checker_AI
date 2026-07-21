import fitz

doc = fitz.open("grading_results/dataset_15919/checked_copy.pdf")

for page_num in range(len(doc)):
    page = doc[page_num]
    text = page.get_text()
    lines = text.split('\n')
    for line in lines:
        if "/" in line:
            print(f"Page {page_num + 1}: {line.strip()}")
