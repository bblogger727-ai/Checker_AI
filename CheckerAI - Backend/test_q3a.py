with open("grading_results/dataset_15919/ocr_output.txt") as f:
    text = f.read()

pages = text.split("=== Page ")
page4_text = ""
for p in pages:
    if p.startswith("4 ==="):
        page4_text = p
        break

print(page4_text)
