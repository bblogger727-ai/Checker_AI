import base64
import io
from PIL import Image
from app.core.openai_client import client


def image_to_base64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def perform_ocr(image: Image.Image) -> str:
    image_b64 = image_to_base64(image)

    response = client.chat.completions.create(
        model="gpt-4o",
        timeout=120,
        messages=[
            {
                "role": "system",
                "content": """You are an OCR engine. Extract all handwritten English text and numbers accurately.

SPATIAL LAYOUT (CRITICAL):
- Reproduce the text with exactly the same spatial arrangement as it appears on the page.
- Each line of handwriting must become exactly one line in your output.
- If the student left a blank line or large gap between sections, preserve that gap with a blank line in the output.
- Words on the same handwritten line must stay on the same output line.
- Do NOT merge multiple lines into one or split one line into multiple lines.
- The vertical position of text in your output should mirror the vertical position in the image as closely as possible.

PRESERVE: numbers, formulas, tables, headings, question numbers. Do not miss any.

STRIKETHROUGH DETECTION (CRITICAL):
- Words/numbers with HORIZONTAL LINES drawn through them are CANCELLED.
- SCRIBBLES or messy cross-outs are also CANCELLED.
- If a student wrote an answer and then crossed it out (e.g. wrote 'a' then crossed it out and wrote 'c'), ONLY transcribe the final valid answer.
- COMPLETELY OMIT cancelled/crossed-out/scribbled text from output.
- If uncertain, err on the side of omitting it.

TABLE EXTRACTION:
- Extract ALL numbers from tables - look at left AND right columns.
- Use markdown table format to preserve structure."""
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract all handwritten text and numbers from this answer sheet image. No words on the page should be missed or changed. There might be words or numbers that are scratched, like a line or multiple lines drawn through the middle of the word, then remove just those words. Do not include them in the output. Draw tables and all their contents appropriately. Maintain the exact spatial layout — same words per line, same gaps between lines, exactly as written on the page."},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_b64}"
                        }
                    }
                ]
            }
        ],
        temperature=0
    )

    return response.choices[0].message.content
