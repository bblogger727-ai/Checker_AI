"""
CheckerAI - AI Exam Evaluator API

FastAPI application with PostgreSQL for full debug storage.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import init_db

# API Routers
from app.api.exams import router as exams_router
from app.api.students import router as students_router

# Legacy routers (for backward compatibility / testing)
from app.api.upload import router as upload_router
from app.api.parse_saved import router as parse_saved_router
from app.api.upload_solution import router as upload_solution_router
from app.api.align_answers import router as align_router
from app.api.model_answers import router as model_answers_router
from app.api.grade_answers import router as grade_router

app = FastAPI(
    title="CheckerAI - AI Exam Evaluator",
    description="AI-powered exam evaluation with full debug storage",
    version="2.1.0"
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    """Initialize database on startup."""
    try:
        init_db()
    except Exception as e:
        print(f"[DB] Init error (will retry on first request): {e}")


@app.get("/")
def root():
    return {
        "name": "CheckerAI API",
        "version": "2.1.0",
        "docs": "/docs",
        "database": "PostgreSQL",
        "debug_storage": True
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


# Main API routes (with PostgreSQL)
app.include_router(exams_router)
app.include_router(students_router)

# Legacy routes (file-based, no auth)
app.include_router(upload_router)
app.include_router(parse_saved_router)
app.include_router(upload_solution_router)
app.include_router(align_router)
app.include_router(model_answers_router)
app.include_router(grade_router)
