import sys, os, json
sys.path.insert(0, '/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend')
from app.services.model_answer_builder import extract_table_answer_via_vision, _render_page_as_base64
from app.core.openai_client import client

def extract_q3_vision(pdf_path, sa_text):
    # Q3 answer is on pages 4 and 5 in 15166sa.pdf
    pages_to_extract = [4, 5]
    print(f"Extracting Q3 from pages {pages_to_extract} via Vision...")
    
    encoded_pages = []
    for p in pages_to_extract:
        b64 = _render_page_as_base64(pdf_path, p)
        if b64:
            encoded_pages.append(b64)
            
    prompt = """You are an expert CA examiner.
    Look at the provided pages from the Suggested Answer (SA) document.
    Extract the ENTIRE MODEL ANSWER for Question 3.
    Extract all tables, text, and calculations exactly as written.
    Return ONLY the extracted text in markdown format. Do not add any conversational text."""

    content_list = [{"type": "text", "text": prompt}]
    for b64 in encoded_pages:
        content_list.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"}
        })

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": content_list}],
        temperature=0
    )
    
    return response.choices[0].message.content.strip()

sa_path = '/Users/gaureshmantri/Desktop/CheckerAI/15166sa.pdf'
with open('/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/pipeline_temp/2_sa_text.txt') as f:
    sa_text = f.read()

q3_ans = extract_q3_vision(sa_path, sa_text)
print("=== Q3 VISION EXTRACTED ANSWER ===")
print(q3_ans[:1000])
