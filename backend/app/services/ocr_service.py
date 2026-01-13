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
        messages=[
            {
                "role": "system",
                "content": "You are an OCR engine. Extract all handwritten English text accurately. Preserve numbers, formulas, tables, headings, and question numbers."
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract all handwritten text from this answer sheet image."},
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
