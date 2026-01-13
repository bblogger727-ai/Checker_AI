from fastapi import FastAPI
from app.api.upload import router as upload_router
from app.api.parse_saved import router as parse_saved_router
from app.api.upload_solution import router as solution_router
from app.api.align_answers import router as align_router
from app.api.model_answers import router as model_answers_router
from app.api.grade_answers import router as grade_router


app = FastAPI(title="AI Exam Evaluator")

app.include_router(upload_router)
app.include_router(parse_saved_router)
app.include_router(solution_router)
app.include_router(align_router)
app.include_router(model_answers_router)
app.include_router(grade_router)


@app.get("/")
def root():
    return {"status": "running"}
