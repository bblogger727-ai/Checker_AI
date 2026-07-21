"""
SetterAI - AI Exam Paper Generator

FastAPI application for generating exam papers for CA students.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.database import init_db

# API Routers
from app.api.subjects import router as subjects_router
from app.api.questions import router as questions_router
from app.api.templates import router as templates_router
from app.api.papers import router as papers_router

app = FastAPI(
    title="SetterAI - Exam Paper Generator",
    description="AI-powered exam paper generation for CA students",
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

class PrivateNetworkAccessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.method == "OPTIONS" and request.headers.get("Access-Control-Request-Private-Network"):
            response.headers["Access-Control-Allow-Private-Network"] = "true"
        return response

app.add_middleware(PrivateNetworkAccessMiddleware)


@app.on_event("startup")
def startup():
    """Initialize database on startup."""
    try:
        init_db()
    except Exception as e:
        print(f"[SetterAI] DB init error: {e}")


@app.get("/")
def root():
    return {
        "name": "SetterAI API",
        "version": "1.0.0",
        "description": "AI Exam Paper Generator",
        "docs": "/docs"
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


# Include routers
app.include_router(subjects_router)
app.include_router(questions_router)
app.include_router(templates_router)
app.include_router(papers_router)
