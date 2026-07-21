with open("grading_results/dataset_15919/ocr_output.txt") as f:
    text = f.read()

pages = text.split("=== Page ")
page2_text = ""
for p in pages:
    if p.startswith("2 ==="):
        page2_text = p
        break

print(page2_text)
