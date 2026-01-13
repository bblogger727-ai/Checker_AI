"""
Database Models for CheckerAI

SQLAlchemy models with FULL debug storage - every pipeline step saved.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()


class Exam(Base):
    """Exam with solution and all generated data for debugging."""
    __tablename__ = "exams"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Basic info
    name = Column(String(255), nullable=False)
    subject = Column(String(255))
    exam_date = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # --- STEP 1: Solution PDF ---
    solution_pdf_path = Column(String(512))
    
    # --- STEP 2: Extracted Text (DEBUG) ---
    solution_text = Column(Text)  # Raw extracted text from PDF
    
    # --- STEP 3: Question Schema (DEBUG) ---
    schema_json = Column(JSON)  # Generated question structure
    schema_raw_response = Column(Text)  # Raw GPT response for debugging
    
    # --- STEP 4: Model Answers (DEBUG) ---
    model_answers_json = Column(JSON)  # Extracted correct answers
    model_answers_raw_response = Column(Text)  # Raw GPT response
    
    # Status tracking
    processing_status = Column(String(50), default="pending")
    processing_error = Column(Text)  # Error message if failed
    
    # Relationships
    student_papers = relationship("StudentPaper", back_populates="exam", cascade="all, delete-orphan")


class StudentPaper(Base):
    """Student answer paper with all grading steps stored for debugging."""
    __tablename__ = "student_papers"
    
    id = Column(Integer, primary_key=True, index=True)
    exam_id = Column(Integer, ForeignKey("exams.id"), nullable=False)
    
    # Student info
    student_name = Column(String(255), nullable=False)
    roll_number = Column(String(50))
    
    # --- STEP 1: Answer PDF ---
    answer_pdf_path = Column(String(512))
    
    # --- STEP 2: OCR Text (DEBUG) ---
    ocr_pages_json = Column(JSON)  # [{page: 1, text: "..."}, ...]
    ocr_combined_text = Column(Text)  # All pages combined
    
    # --- STEP 3: Parsed Answers (DEBUG) ---
    parsed_answers_json = Column(JSON)  # Raw parsed from OCR
    parsed_raw_response = Column(Text)  # Raw GPT response
    
    # --- STEP 4: Aligned Answers (DEBUG) ---
    aligned_answers_json = Column(JSON)  # Aligned to schema
    aligned_raw_response = Column(Text)  # Raw GPT response
    
    # --- STEP 5: Grading Results (DEBUG) ---
    grading_json = Column(JSON)  # Full grading output
    grading_raw_responses = Column(JSON)  # All GPT responses for grading
    
    # --- STEP 6: Result PDF ---
    graded_pdf_path = Column(String(512))
    
    # Summary scores
    total_marks = Column(Integer)
    obtained_marks = Column(Integer)
    percentage = Column(Integer)
    grade = Column(String(5))
    
    # Status and timestamps
    status = Column(String(50), default="pending")
    processing_error = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    ocr_completed_at = Column(DateTime)
    aligned_at = Column(DateTime)
    graded_at = Column(DateTime)
    
    # Relationships
    exam = relationship("Exam", back_populates="student_papers")
