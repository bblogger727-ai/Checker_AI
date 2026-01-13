from pdf2image import convert_from_bytes
from typing import List
from PIL import Image
import io

def pdf_to_images(pdf_bytes: bytes) -> List[Image.Image]:
    images = convert_from_bytes(pdf_bytes, dpi = 150)
    return images
