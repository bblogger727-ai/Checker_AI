"""
MentorAI - Student Progress & Mentoring System

FastAPI application for tracking student progress and generating personalized reports.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import init_db

# API Routers
from app.api.students import router as students_router
from app.api.problems import router as problems_router
from app.api.consultations import router as consultations_router
from app.api.dashboard import router as dashboard_router
from app.api.link import router as link_router

app = FastAPI(
    title="MentorAI - Student Mentoring System",
    description="Track student progress, manage consultations, and generate personalized reports",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    """Initialize database and seed problems on startup."""
    try:
        init_db()
        print("[MentorAI] Database initialized", flush=True)
    except Exception as e:
        print(f"[MentorAI] DB init error: {e}", flush=True)


@app.get("/")
def root():
    return {
        "name": "MentorAI API",
        "version": "1.0.0",
        "description": "Student Progress & Mentoring System",
        "docs": "/docs"
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


# Include routers
app.include_router(students_router)
app.include_router(problems_router)
app.include_router(consultations_router)
app.include_router(dashboard_router)
app.include_router(link_router)
