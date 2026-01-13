"""
MentorAI Database Models

Student progress tracking, consultations, and problem management.
"""

from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class Student(Base):
    """Student profile with contact info and performance tracking."""
    __tablename__ = "mentor_students"
    
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(String(20), unique=True, index=True)  # e.g., "STU001"
    name = Column(String(200), nullable=False, index=True)
    phone = Column(String(20))  # WhatsApp number
    email = Column(String(200))
    
    enrollment_date = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text)  # General notes about student
    
    # Relationships
    exams = relationship("StudentExam", back_populates="student", cascade="all, delete-orphan")
    consultations = relationship("Consultation", back_populates="student", cascade="all, delete-orphan")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<Student {self.student_id}: {self.name}>"


class StudentExam(Base):
    """Exam results linked from CheckerAI."""
    __tablename__ = "mentor_student_exams"
    
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("mentor_students.id"), nullable=False)
    
    # Link to CheckerAI
    checker_paper_id = Column(Integer)  # FK to CheckerAI student_papers
    
    # Exam details
    exam_name = Column(String(200))
    subject = Column(String(100))
    exam_date = Column(DateTime)
    
    # Scores
    total_marks = Column(Float)
    obtained_marks = Column(Float)
    percentage = Column(Float)
    grade = Column(String(10))
    
    # Full grading result (from CheckerAI)
    grading_json = Column(JSON)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    student = relationship("Student", back_populates="exams")


class ProblemCategory(Base):
    """Categories for problems (Health, Mindset, etc.)."""
    __tablename__ = "mentor_problem_categories"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    icon = Column(String(10))  # Emoji
    order_index = Column(Integer, default=0)
    
    # Relationships
    problems = relationship("Problem", back_populates="category")


class Problem(Base):
    """Predefined and custom problems."""
    __tablename__ = "mentor_problems"
    
    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey("mentor_problem_categories.id"))
    
    title = Column(String(200), nullable=False)
    description = Column(Text)
    default_solution = Column(Text)  # Template solution
    
    is_custom = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    category = relationship("ProblemCategory", back_populates="problems")


class Consultation(Base):
    """Mentoring session record."""
    __tablename__ = "mentor_consultations"
    
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("mentor_students.id"), nullable=False)
    
    consultation_date = Column(DateTime, default=datetime.utcnow)
    
    # Problems selected
    problems_json = Column(JSON)  # [{problem_id, notes}]
    custom_problem_text = Column(Text)  # If "Other" selected
    
    mentor_notes = Column(Text)
    
    # LLM Debug Info
    llm_prompt = Column(Text)
    llm_response = Column(Text)
    generated_solution = Column(Text)
    
    # Report
    report_pdf_path = Column(String(500))
    
    # Delivery
    sent_via = Column(String(50))  # "whatsapp", "email", "both"
    sent_at = Column(DateTime)
    delivery_status = Column(String(50), default="pending")  # pending, sent, failed
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    student = relationship("Student", back_populates="consultations")
