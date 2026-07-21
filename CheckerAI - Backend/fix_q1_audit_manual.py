
import os
import json
import re
import sys
from dotenv import load_dotenv
load_dotenv()
import anthropic

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
CLAUDE_MODEL = "claude-sonnet-4-20250514"

def fix_q1():
    dataset_dir = "/Users/gaureshmantri/Desktop/CheckerAI/CheckerAI - Backend/grading_results/dataset_Audit_Final"
    feedback_path = os.path.join(dataset_dir, "feedback_final.json")
    ocr_path = os.path.join(dataset_dir, "ocr_output.txt")
    model_pdf = "/Users/gaureshmantri/Desktop/CheckerAI/Audit ModelSheet.pdf"
    marks_path = os.path.join(dataset_dir, "student_marks.json")

    # 1. Load existing feedback
    with open(feedback_path, "r") as f:
        feedback_data = json.load(f)

    # 2. Load OCR text
    with open(ocr_path, "r") as f:
        ocr_text = f.read()

    # 3. Load Student Marks
    with open(marks_path, "r") as f:
        student_marks = json.load(f).get("marks", {})

    # 4. Extract Q1 Question & Model Answers (Targeted)
    # I'll use a single Claude call for all three Q1 parts to be efficient.
    print("Extracting Q1a, Q1b, Q1c from Model Sheet...")
    
    # We already have the text from previous steps, but to be sure we get the full text:
    import fitz
    doc = fitz.open(model_pdf)
    q_text = ""
    for i in range(10, 16): # Pages 11 to 16
        q_text += doc[i].get_text()
    
    prompt = f"""
    Extract Question 1 subparts (a, b, c) from this text.
    Return a JSON object exactly like this:
    {{
      "Q1a": {{"question_text": "...", "model_answer": "...", "total_marks": 5}},
      "Q1b": {{"question_text": "...", "model_answer": "...", "total_marks": 5}},
      "Q1c": {{"question_text": "...", "model_answer": "...", "total_marks": 4}}
    }}
    
    TEXT:
    {q_text}
    """
    
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    
    # Parse JSON (naive)
    match = re.search(r'\{.*\}', resp.content[0].text, re.DOTALL)
    q1_data = json.loads(match.group())

    # 5. Align each with OCR
    print("Aligning Q1a, Q1b, Q1c with student OCR...")
    for qid in ["Q1a", "Q1b", "Q1c"]:
        q_info = q1_data[qid]
        align_prompt = f"""
        Find the student's answer for {qid} in this OCR text.
        Question: {q_info['question_text'][:200]}...
        
        OCR TEXT:
        {ocr_text}
        
        Return ONLY the raw text of the student's answer and the page numbers as JSON:
        {{"student_answer": "...", "pages": [1, 2]}}
        """
        align_resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": align_prompt}],
            temperature=0
        )
        align_match = re.search(r'\{.*\}', align_resp.content[0].text, re.DOTALL)
        align_info = json.loads(align_match.group())
        
        # 6. Generate Feedback
        print(f"Generating feedback for {qid}...")
        scored_marks = student_marks.get(qid, 0)
        feedback_prompt = f"""
        Evaluate the student's answer against the model answer.
        Question: {q_info['question_text']}
        Model Answer: {q_info['model_answer']}
        Student Answer: {align_info['student_answer']}
        Marks Scored: {scored_marks} / {q_info['total_marks']}
        
        Provide mentor-style feedback in JSON format:
        {{
          "marks_summary": "{scored_marks} / {q_info['total_marks']}",
          "what_went_right": "...",
          "what_went_wrong": "...",
          "conclusion": "..."
        }}
        """
        fb_resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": feedback_prompt}],
            temperature=0
        )
        fb_match = re.search(r'\{.*\}', fb_resp.content[0].text, re.DOTALL)
        fb_info = json.loads(fb_match.group())
        
        # 7. Merge into feedback_data
        feedback_data[qid] = {
            "question_id": qid,
            "question_number": "Q1",
            "subpart": qid[2:],
            "question_text": q_info["question_text"],
            "marks": q_info["total_marks"],
            "model_answer": q_info["model_answer"],
            "student_answer": align_info["student_answer"],
            "answer_pages": align_info["pages"],
            "marks_scored": scored_marks,
            "feedback": fb_info
        }

    # 8. Save updated feedback
    with open(feedback_path, "w") as f:
        json.dump(feedback_data, f, indent=2, ensure_ascii=False)
    
    print("\n✓ Successfully merged Q1a, Q1b, Q1c into feedback_final.json")

if __name__ == "__main__":
    fix_q1()
