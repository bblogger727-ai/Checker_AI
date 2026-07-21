import json
import os
from app.core.database import SessionLocal, init_db
from app.models import Exam, StudentPaper
from datetime import datetime

init_db()
db = SessionLocal()

# Create dummy exam if not exists
exam = db.query(Exam).filter(Exam.id == 1).first()
if not exam:
    exam = Exam(id=1, name="Mock Exam", subject="Mock Subject", processing_status="completed")
    db.add(exam)
    db.commit()

# Load 15935
student_id = 15935
student = db.query(StudentPaper).filter(StudentPaper.id == student_id).first()
if not student:
    student = StudentPaper(id=student_id, exam_id=1, student_name="Student 15935", status="completed")
    db.add(student)

# Set properties
student.answer_pdf_path = f"grading_results/dataset_{student_id}/checked_copy.pdf"
student.graded_pdf_path = f"grading_results/dataset_{student_id}/checked_copy.pdf"
try:
    with open(f"grading_results/dataset_{student_id}/grading_final.json", "r") as f:
        student.grading_json = json.load(f)
except Exception as e:
    print(f"No grading json: {e}")

db.commit()
print("Injected 15935!")
db.close()
