import pdfplumber


def extract_solution_text(pdf_path: str) -> str:
    full_text = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(layout=True)

            if text:
                full_text.append(
                    f"\n\n========== PAGE {page_number} ==========\n\n"
                )
                full_text.append(text)

    return "\n".join(full_text)
