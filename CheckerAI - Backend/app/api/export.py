"""
Read-only export for the Gradence Mentorship Program.

  GET /api/export/papers           every paper in All_Paper_JSONs, with its questions
  GET /api/export/checked?after=   every checked paper's per-question marks

Nothing here writes. Answer text, model answers and feedback are left out: the mentorship
side needs marks, tiers, skips and the checker's error notes, not what the student wrote.
Protected like every /api/ route by the login gate (service token).
"""

import json
import re
from pathlib import Path

from fastapi import APIRouter, Query

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_JOBS_DIR = _BACKEND_DIR.parent / "pipeline_jobs"
_PAPERS_DIR = _BACKEND_DIR.parent / "All_Paper_JSONs"

router = APIRouter(prefix="/api/export", tags=["Export"])

_HEAVY = {"question", "question_text", "student_answer", "model_answer", "feedback",
          "correct_lines", "wrong_lines", "answer_pages", "correct_calculations",
          "incorrect_calculations"}


def _kind(stem: str) -> str:
    if "_Mock_" in stem:
        return "mock"
    if "_Portionwise_" in stem:
        return "portionwise"
    if "_Chapter_" in stem or stem.startswith("QA_Chapter"):
        return "chapter"
    return "other"


def _question(item: dict, qid: str, section: str, marks=None) -> dict:
    return {
        "qid": qid, "section": section,
        "marks": item.get("marks") or item.get("total_marks") or marks,
        "chapter_number": str(item.get("chapter_number") or "") or None,
        "chapter_name": str(item.get("chapter_name") or item.get("chapter") or "").strip(),
        "mcq": bool(item.get("options")) or item.get("type") == "case_study",
        "text": str(item.get("question") or item.get("case_text") or "")[:400],
    }


def _paper(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    stem = path.stem
    meta = data.get("meta") or {} if isinstance(data, dict) else {}
    subject = meta.get("subject_code") or re.split(r"_(Mock|Portionwise|Chapter)_", stem)[0]
    questions = []
    if isinstance(data, list):  # Foundation chapter tests: a flat list of questions
        for i, item in enumerate(data, 1):
            if isinstance(item, dict):
                questions.append(_question(item, f"Q{item.get('q_num') or i}", "main"))
    else:
        for section in ("section_a", "section_b"):
            for i, q in enumerate(data.get(section) or [], 1):
                if not isinstance(q, dict):
                    continue
                main = q.get("q_main") or q.get("q_num")
                if main is None:  # e.g. a case study with its MCQs (Section A)
                    questions.append(_question(q, f"{section[-1].upper()}{i}", section))
                    continue
                for sub in q.get("sub_questions") or [None]:
                    item = {**q, **(sub or {})}
                    questions.append(_question(item, f"Q{main}{(sub or {}).get('label') or ''}",
                                               section, q.get("total_marks")))
    return {
        "id": f"{path.parent.name}/{stem}", "exam": path.parent.name, "subject_code": subject,
        "subject_name": meta.get("subject_name") or subject.replace("_", " "),
        "kind": _kind(stem), "label": stem.replace("_", " "),
        "total_marks": meta.get("total_marks_printed") or meta.get("total_marks_in_paper")
        or sum(q["marks"] or 0 for q in questions) or None,
        "questions": questions,
    }


@router.get("/papers")
def export_papers():
    papers = []
    if _PAPERS_DIR.exists():
        for path in sorted(_PAPERS_DIR.glob("*/*.json")):
            try:
                papers.append(_paper(path))
            except (OSError, ValueError, AttributeError, TypeError) as error:
                papers.append({"id": f"{path.parent.name}/{path.stem}", "error": str(error)[:200]})
    return {"papers": papers}


def _slim(node):
    if isinstance(node, dict):
        out = {k: _slim(v) for k, v in node.items() if k not in _HEAVY}
        if "marks_total" in node:
            out["has_answer"] = bool(str(node.get("student_answer") or "").strip())
        return out
    if isinstance(node, list):
        return [_slim(v) for v in node]
    return node


@router.get("/checked")
def export_checked(after: float = Query(default=0.0, ge=0)):
    """Checked papers whose grading finished after `after` (a Unix time), oldest first."""

    jobs = []
    if _JOBS_DIR.exists():
        for job_dir in _JOBS_DIR.iterdir():
            grading_file = job_dir / "grading_final.json"
            meta_file = job_dir / "task_meta.json"
            if not grading_file.is_file():
                continue
            finished = grading_file.stat().st_mtime
            if finished <= after:
                continue
            try:
                grading = json.loads(grading_file.read_text(encoding="utf-8"))
                meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
            except (OSError, ValueError):
                continue
            paper_path = Path(str(meta.get("ft_paper_path") or ""))
            jobs.append({
                "task_id": job_dir.name,
                "student": str(meta.get("student_name") or "").strip(),
                "paper_id": f"{paper_path.parent.name}/{paper_path.stem}" if paper_path.stem else None,
                "paper_label": meta.get("paper_label"),
                "created_at": meta.get("created_at"),
                "finished_at": finished,
                "summary": {k: grading.get("metadata", {}).get(k) for k in (
                    "total_marks_obtained", "total_marks_possible", "percentage", "grade",
                    "scoring_rule", "top5_questions")},
                "graded_answers": _slim(grading.get("graded_answers") or {}),
            })
    jobs.sort(key=lambda j: j["finished_at"])
    return {"jobs": jobs}
