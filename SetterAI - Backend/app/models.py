"""
SetterAI Database Models

Models for paper generation: subjects, question bank, templates, generated papers.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()


class Subject(Base):
    """CA Subject with syllabus and marking scheme."""
    __tablename__ = "subjects"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)  # "Advanced Accounting"
    code = Column(String(20), unique=True)  # "AA", "DT", "IDT"
    level = Column(String(50))  # "Foundation", "Inter", "Final"
    
    # Syllabus structure with topic weights
    syllabus_json = Column(JSON)
    # {
    #   "topics": [
    #     {"name": "AS 24 - Discontinuing Operations", "weight": 0.15},
    #     {"name": "Business Combinations", "weight": 0.20}
    #   ]
    # }
    
    # Marking scheme and format rules
    marking_scheme_json = Column(JSON)
    # {
    #   "total_marks": 100,
    #   "duration_minutes": 180,
    #   "sections": {...}
    # }
    
    # Reference materials
    notes_pdf_paths = Column(JSON)  # List of PDF paths
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
    
    # Relationships
    questions = relationship("QuestionBank", back_populates="subject")
    templates = relationship("PaperTemplate", back_populates="subject")
    papers = relationship("GeneratedPaper", back_populates="subject")


class QuestionBank(Base):
    """Question bank with PYQs and generated questions."""
    __tablename__ = "question_bank"
    
    id = Column(Integer, primary_key=True, index=True)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    
    # Question content
    question_text = Column(Text, nullable=False)
    question_type = Column(String(50))  # "MCQ", "Descriptive", "Practical", "Case Study"
    marks = Column(Integer, nullable=False)  # 1, 4, 8, 16
    
    # Classification
    topic = Column(String(255))  # Main topic
    subtopic = Column(String(255))  # Subtopic
    difficulty = Column(String(50))  # "Easy", "Medium", "Hard"
    
    # PYQ metadata
    pyq_year = Column(Integer)  # 2023, 2022, null if custom
    pyq_session = Column(String(50))  # "May", "Nov"
    frequency_score = Column(Float, default=0.0)  # How often similar appears
    
    # Answer
    model_answer = Column(Text)
    options_json = Column(JSON)  # For MCQs: {"a": "...", "b": "...", "correct": "a"}
    
    # Source tracking
    source_pdf = Column(String(512))
    source_page = Column(Integer)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    subject = relationship("Subject", back_populates="questions")


class PaperTemplate(Base):
    """Paper format templates (Full Test, Portionwise, Mock)."""
    __tablename__ = "paper_templates"
    
    id = Column(Integer, primary_key=True, index=True)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    
    name = Column(String(255), nullable=False)  # "Full Practice Test"
    paper_type = Column(String(50))  # "Full", "Portionwise", "Mock", "Topic-wise"
    
    total_marks = Column(Integer)
    duration_minutes = Column(Integer)
    
    # Format structure
    format_json = Column(JSON)
    # {
    #   "sections": [
    #     {
    #       "name": "Section A - MCQs",
    #       "marks": 20,
    #       "question_count": 20,
    #       "question_type": "MCQ",
    #       "compulsory": true,
    #       "topic_filter": null
    #     },
    #     {
    #       "name": "Section B - Descriptive",
    #       "marks": 40,
    #       "question_count": 4,
    #       "choose": 3,
    #       "question_type": "Descriptive",
    #       "marks_per_question": 10
    #     }
    #   ]
    # }
    
    # Topic restrictions (for portionwise)
    topics_included = Column(JSON)  # List of topic names
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    subject = relationship("Subject", back_populates="templates")
    papers = relationship("GeneratedPaper", back_populates="template")


class GeneratedPaper(Base):
    """AI-generated exam papers with edit history."""
    __tablename__ = "generated_papers"
    
    id = Column(Integer, primary_key=True, index=True)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False)
    template_id = Column(Integer, ForeignKey("paper_templates.id"))
    
    title = Column(String(255))  # "DT Practice Test - Jan 2026"
    
    # Status flow: draft -> reviewing -> finalized -> published
    status = Column(String(50), default="draft")
    
    # Paper content at different stages
    generated_paper_json = Column(JSON)  # Initial AI generation
    edited_paper_json = Column(JSON)  # After user edits
    final_paper_json = Column(JSON)  # Finalized version
    
    # Solution
    solution_json = Column(JSON)  # Auto-generated solution
    solution_pdf_path = Column(String(512))
    
    # Link to CheckerAI
    linked_exam_id = Column(Integer)  # FK to CheckerAI exams table
    
    # Generation metadata
    generation_config = Column(JSON)  # Options used for generation
    ai_raw_response = Column(Text)  # Debug: raw LLM response
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    edited_at = Column(DateTime)
    finalized_at = Column(DateTime)
    published_at = Column(DateTime)
    
    # Relationships
    subject = relationship("Subject", back_populates="papers")
    template = relationship("PaperTemplate", back_populates="papers")
