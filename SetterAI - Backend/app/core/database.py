"""
Database Connection for SetterAI

Uses the same PostgreSQL instance as CheckerAI.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

# Same database as CheckerAI
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/checkerai")

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Dependency for FastAPI - yields database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize SetterAI tables."""
    from app.models import Base
    Base.metadata.create_all(bind=engine)
    print("[SetterAI] Database tables created/verified")
