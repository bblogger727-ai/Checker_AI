"""
Pipelines API — Direct Grading Pipelines
=========================================
Exposes three endpoints for the CheckerAI Dashboard:

  GET  /api/pipelines/catalog
       Scans All_Paper_JSONs and returns a structured catalog of every paper
       grouped by exam (Foundation/Inter/Final), subject, and type (Mock/Portionwise).

  POST /api/pipelines/run/old
       Old-Papers Checking: accepts QP + SA + AS PDFs, launches
       run_pipeline_claude_api.py in a background thread, returns a task_id.

  POST /api/pipelines/run/new
       New-Papers Checking (FT): accepts AS PDF + a paper catalog key,
       launches run_pipeline_FT_api.py in a background thread, returns a task_id.

  GET  /api/pipelines/status/{task_id}
       Returns the current result.json (stage, message, progress, paths when done).

  GET  /api/pipelines/download/{task_id}/{file_type}
       Streams the finished checked_copy.pdf or grading_report.pdf to the browser.
"""

import os
import sys
import uuid
import json
import time
import threading
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

# ── Directory layout ─────────────────────────────────────────────────────────
_HERE           = Path(__file__).resolve().parent              # app/api/
_APP_DIR        = _HERE.parent                                  # app/
_BACKEND_DIR    = _APP_DIR.parent                               # CheckerAI - Backend/
_JOBS_DIR       = _BACKEND_DIR / "pipeline_jobs"               # one subdir per task_id
_PAPERS_DIR     = _BACKEND_DIR.parent / "All_Paper_JSONs"      # the JSON catalog

_CLAUDE_SCRIPT  = _BACKEND_DIR / "run_pipeline_claude_api.py"
_FT_SCRIPT      = _BACKEND_DIR / "run_pipeline_FT_api.py"

router = APIRouter(prefix="/api/pipelines", tags=["Pipelines"])


# ══════════════════════════════════════════════════════════════════════════════
# Paper catalog
# ══════════════════════════════════════════════════════════════════════════════

def _build_catalog() -> dict:
    """
    Scan All_Paper_JSONs/{Exam}/{Subject_File.json} and parse filenames into
    a structured dict:

    {
      "Final": {
        "AA": {
          "Mock":       [ { "label": "Mock Paper 1", "path": "...", "filename": "AA_Mock_Paper_1.json" }, ... ],
          "Portionwise": [ ... ]
        },
        ...
      },
      ...
    }
    """
    catalog: dict = {}

    if not _PAPERS_DIR.exists():
        return catalog

    for exam_dir in sorted(_PAPERS_DIR.iterdir()):
        if not exam_dir.is_dir():
            continue
        exam_name = exam_dir.name          # Foundation / Inter / Final
        catalog[exam_name] = {}

        for json_file in sorted(exam_dir.glob("*.json")):
            stem = json_file.stem          # e.g. "AA_Mock_Paper_1"
            parts = stem.split("_")

            # Heuristic: subject is everything before "Mock" or "Portionwise"
            try:
                if "Mock" in parts:
                    split_idx = parts.index("Mock")
                    ptype     = "Mock"
                elif "Portionwise" in parts:
                    split_idx = parts.index("Portionwise")
                    ptype     = "Portionwise"
                else:
                    continue   # skip unknown format

                subject = "_".join(parts[:split_idx])
                # Friendly label: e.g. "Mock Paper 1" from "Mock_Paper_1"
                tail    = "_".join(parts[split_idx:])
                label   = tail.replace("_", " ")

            except Exception:
                continue

            catalog.setdefault(exam_name, {})
            catalog[exam_name].setdefault(subject, {"Mock": [], "Portionwise": []})
            catalog[exam_name][subject][ptype].append({
                "label":    label,
                "path":     str(json_file),
                "filename": json_file.name,
            })

    return catalog


@router.get("/catalog")
def get_paper_catalog():
    """Return the structured catalog of all available FT paper JSONs."""
    return JSONResponse(content=_build_catalog())


# ══════════════════════════════════════════════════════════════════════════════
# In-memory task store  (good enough for a single-server deployment)
# ══════════════════════════════════════════════════════════════════════════════

_tasks: dict[str, dict] = {}   # task_id → { status, output_dir, thread }


def _save_upload(upload: UploadFile, dest: Path):
    content = upload.file.read()
    dest.write_bytes(content)


def _run_subprocess(task_id: str, cmd: list[str], output_dir: Path):
    """Run a pipeline subprocess and monitor it. Updates _tasks on completion."""
    _tasks[task_id]["status"] = "running"
    _tasks[task_id]["pid"]    = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(_BACKEND_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        _tasks[task_id]["pid"] = proc.pid

        # Stream stdout to a log file
        log_path = output_dir / "pipeline.log"
        with log_path.open("w") as log_f:
            for line in proc.stdout:
                log_f.write(line)
                log_f.flush()

        proc.wait()
        if proc.returncode == 0:
            _tasks[task_id]["status"] = "done"
        else:
            _tasks[task_id]["status"] = "failed"
            _tasks[task_id]["error"]  = f"Process exited with code {proc.returncode}"

    except Exception as e:
        _tasks[task_id]["status"] = "failed"
        _tasks[task_id]["error"]  = str(e)


# ══════════════════════════════════════════════════════════════════════════════
# Run: Old Papers Checking (Claude pipeline)
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/run/old")
async def run_old_pipeline(
    student_name: str       = Form(""),
    qp_pdf:       UploadFile = File(..., description="Question Paper PDF"),
    sa_pdf:       UploadFile = File(..., description="Solution / Model Answer PDF"),
    as_pdf:       UploadFile = File(..., description="Student Answer Sheet PDF"),
):
    """
    Launch the Old-Papers Claude grading pipeline (Stages 1–7) in the background.

    Returns immediately with a `task_id` — poll `/api/pipelines/status/{task_id}`
    for progress updates.
    """
    safe_name = "".join([c if c.isalnum() else "_" for c in student_name.strip()]).strip("_")
    task_id   = f"{safe_name}_{uuid.uuid4().hex}" if safe_name else uuid.uuid4().hex
    output_dir = _JOBS_DIR / task_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save uploads
    qp_path = output_dir / "question_paper.pdf"
    sa_path = output_dir / "solution.pdf"
    as_path = output_dir / "student_answersheet.pdf"
    _save_upload(qp_pdf, qp_path)
    _save_upload(sa_pdf, sa_path)
    _save_upload(as_pdf, as_path)

    # Save metadata
    meta = {
        "pipeline":    "old",
        "student_name": student_name,
        "task_id":     task_id,
        "created_at":  time.time(),
    }
    (output_dir / "task_meta.json").write_text(json.dumps(meta, indent=2))

    # Kick off the subprocess in a background thread
    cmd = [
        sys.executable,
        str(_CLAUDE_SCRIPT),
        "--qp",         str(qp_path),
        "--sa",         str(sa_path),
        "--as",         str(as_path),
        "--output-dir", str(output_dir),
        "--dataset",    f"old_{task_id[:8]}",
    ]

    _tasks[task_id] = {"status": "queued", "output_dir": str(output_dir), "pipeline": "old"}
    t = threading.Thread(target=_run_subprocess, args=(task_id, cmd, output_dir), daemon=True)
    t.start()
    _tasks[task_id]["thread"] = t

    return {"task_id": task_id, "status": "queued"}


# ══════════════════════════════════════════════════════════════════════════════
# Run: New Papers Checking (FT pipeline)
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/run/new")
async def run_new_pipeline(
    student_name:    str       = Form(""),
    ft_paper_path:   str       = Form(..., description="Absolute path to the selected FT paper JSON"),
    as_pdf:          UploadFile = File(..., description="Student Answer Sheet PDF"),
):
    """
    Launch the New-Papers FT grading pipeline (Stages 1–7) in the background.

    `ft_paper_path` is the absolute path of the JSON returned by `/catalog`
    (e.g. `/Users/.../All_Paper_JSONs/Final/AA_Mock_Paper_3.json`).

    Returns immediately with a `task_id`.
    """
    # Validate the paper path belongs to our catalog dir (basic security check)
    try:
        paper_path = Path(ft_paper_path).resolve()
        paper_path.relative_to(_PAPERS_DIR.resolve())   # raises ValueError if outside
    except (ValueError, FileNotFoundError):
        raise HTTPException(status_code=400, detail="Invalid paper path — must be from the catalog")

    if not paper_path.exists():
        raise HTTPException(status_code=404, detail=f"Paper JSON not found: {ft_paper_path}")

    safe_name = "".join([c if c.isalnum() else "_" for c in student_name.strip()]).strip("_")
    task_id   = f"{safe_name}_{uuid.uuid4().hex}" if safe_name else uuid.uuid4().hex
    output_dir = _JOBS_DIR / task_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save upload
    as_path = output_dir / "student_answersheet.pdf"
    _save_upload(as_pdf, as_path)

    meta = {
        "pipeline":      "new",
        "student_name":  student_name,
        "ft_paper_path": str(paper_path),
        "task_id":       task_id,
        "created_at":    time.time(),
    }
    (output_dir / "task_meta.json").write_text(json.dumps(meta, indent=2))

    cmd = [
        sys.executable,
        str(_FT_SCRIPT),
        "--FT",         str(paper_path),
        "--as",         str(as_path),
        "--output-dir", str(output_dir),
        "--dataset",    f"new_{task_id[:8]}",
    ]

    _tasks[task_id] = {"status": "queued", "output_dir": str(output_dir), "pipeline": "new"}
    t = threading.Thread(target=_run_subprocess, args=(task_id, cmd, output_dir), daemon=True)
    t.start()
    _tasks[task_id]["thread"] = t

    return {"task_id": task_id, "status": "queued"}


@router.post("/run/feedback")
async def run_feedback_pipeline(
    student_name: str = Form(""),
    marks_json_str: str = Form(...),
    sa_pdf: UploadFile = File(...),
    as_pdf: UploadFile = File(...),
):
    """
    Runs the specialized CA Feedback Pipeline.
    Takes Solution (sa), Answer Sheet (as) and a stringified JSON of marks.
    """
    task_id = uuid.uuid4().hex
    job_dir = _JOBS_DIR / task_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # Save uploaded files
    sa_path = job_dir / "solution.pdf"
    as_path = job_dir / "student_answersheet.pdf"
    
    _save_upload(sa_pdf, sa_path)
    _save_upload(as_pdf, as_path)
        
    # Write marks JSON to file
    marks_path = job_dir / "student_marks.json"
    marks_path.write_text(marks_json_str, encoding="utf-8")

    meta = {
        "student_name": student_name,
        "type": "feedback"
    }
    _init_status(job_dir, meta)

    # Prepare command
    script_path = _BACKEND_DIR / "run_pipeline_ca_feedback_api.py"
    cmd = [
        sys.executable, str(script_path),
        "--output-dir", str(job_dir),
        "--sa", str(sa_path),
        "--as-pdf", str(as_path),
        "--marks-json", str(marks_path),
        "--task-id", task_id
    ]

    def run_job():
        try:
            print(f"[Feedback] Launching job {task_id}")
            subprocess.Popen(cmd, cwd=str(_BACKEND_DIR))
        except Exception as e:
            print(f"Error launching Feedback pipeline: {e}")

    thread = threading.Thread(target=run_job)
    thread.start()

    return {"task_id": task_id, "status": "started"}


# ══════════════════════════════════════════════════════════════════════════════
# Status polling
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/status/{task_id}")
def get_pipeline_status(task_id: str):
    """
    Poll the status of a running or completed pipeline job.

    Returns:
      { stage, message, status (queued|running|done|failed), error?, ...output_paths }
    """
    task = _tasks.get(task_id)
    if not task:
        # Task might have been lost (server restart). Check the file.
        job_dir = _JOBS_DIR / task_id
        result_file = job_dir / "result.json"
        if result_file.exists():
            data = json.loads(result_file.read_text())
            data["status"] = "done" if data.get("stage") == "completed" else data.get("stage", "unknown")
            return JSONResponse(content=data)
        raise HTTPException(status_code=404, detail="Task not found")

    output_dir   = Path(task["output_dir"])
    result_file  = output_dir / "result.json"

    base = {
        "task_id":  task_id,
        "status":   task["status"],
        "pipeline": task.get("pipeline"),
        "error":    task.get("error"),
    }

    if result_file.exists():
        result_data = json.loads(result_file.read_text())
        base.update(result_data)

    # Attach availability flags for download links
    base["checked_copy_ready"]   = (output_dir / "checked_copy.pdf").exists()
    base["grading_report_ready"] = (output_dir / "grading_report.pdf").exists()

    return JSONResponse(content=base)


# ══════════════════════════════════════════════════════════════════════════════
# Download completed files
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/download/{task_id}/{file_type}")
def download_pipeline_result(task_id: str, file_type: str):
    """
    Download a completed pipeline output.

    file_type: "checked_copy" | "grading_report"
    """
    job_dir = _JOBS_DIR / task_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Task not found")

    file_map = {
        "checked_copy":   ("checked_copy.pdf",   "checked_copy_edited.pdf"),
        "grading_report": ("grading_report.pdf",  "grading_report.pdf"),
        "student_report": ("student_report.txt",  "student_report.txt"),
    }

    if file_type not in file_map:
        raise HTTPException(status_code=400, detail=f"Unknown file_type: {file_type}")

    filename, download_name = file_map[file_type]
    file_path = job_dir / filename
    
    # If a patched version exists (edited via UI), prefer it for download
    if file_type == "checked_copy":
        patched_path = job_dir / "checked_copy_patched.pdf"
        if patched_path.exists():
            file_path = patched_path

    # Try to get a nicer download filename from metadata
    meta_file = job_dir / "task_meta.json"
    if meta_file.exists():
        meta = json.loads(meta_file.read_text())
        student = meta.get("student_name", "student").replace(" ", "_")
        if file_type == "checked_copy":
            download_name = f"{student}_checked_copy.pdf"
        elif file_type == "grading_report":
            download_name = f"{student}_grading_report.pdf"
        elif file_type == "student_report":
            download_name = f"{student}_report.txt"

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"{filename} not yet available")

    media_type = "application/pdf"
    if filename.endswith(".txt"):
        media_type = "text/plain"

    return FileResponse(
        path=file_path,
        filename=download_name,
        media_type=media_type
    )

# ══════════════════════════════════════════════════════════════════════════════
# Mock endpoints for UI compatibility
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/student/{task_id}")
def get_pipeline_student_mock(task_id: str):
    """
    Returns a mock StudentDetailResponse for the Edit Checked Copy page
    since pipeline jobs are not saved in Postgres.
    """
    job_dir = _JOBS_DIR / task_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Pipeline task not found")
        
    student_name = "Student"
    meta_file = job_dir / "task_meta.json"
    if meta_file.exists():
        meta = json.loads(meta_file.read_text())
        student_name = meta.get("student_name", "Student") or "Student"
        
    result_file = job_dir / "result.json"
    total_obtained, max_total = 0.0, 0.0
    if result_file.exists():
        res = json.loads(result_file.read_text())
        total_obtained = res.get("total_marks_obtained", 0.0)
        max_total = res.get("total_marks_possible", 0.0)
        
    return {
        "id": task_id,
        "exam_id": 0,
        "student_name": student_name,
        "roll_number": "N/A",
        "status": "completed",
        "obtained_marks": total_obtained,
        "total_marks": max_total,
        "percentage": (total_obtained / max_total * 100) if max_total else 0,
        "grade": "N/A",
        "checked_copy_available": (job_dir / "checked_copy.pdf").exists(),
        "ocr_combined_text": None,
        "aligned_answers_json": None,
        "grading_json": None
    }


@router.get("/manifest/{task_id}")
def get_pipeline_manifest(task_id: str):
    """
    Returns the annotation manifest for a pipeline task.
    """
    job_dir = _JOBS_DIR / task_id
    manifest_path = job_dir / "checked_copy_manifest.json"
    if not manifest_path.exists():
        raise HTTPException(
            status_code=404, 
            detail="Annotation manifest not found. Please check this paper again to generate it."
        )
    
    # We use the existing summary helper
    import sys, os
    # Add root to sys.path to import patch_checked_copy
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)
        
    from patch_checked_copy import get_manifest_summary
    return get_manifest_summary(str(manifest_path))



@router.post("/recheck/{task_id}")
async def recheck_pipeline(task_id: str):
    """
    Re-run ONLY Stage 7 (generate_checked_copy_v2) for an existing job.

    Looks up the job directory for:
      - student_answersheet.pdf
      - grading_final.json
      - aligned_answers.json
      - 3_ocr_output.txt  (optional, falls back gracefully if missing)

    Overwrites checked_copy.pdf and checked_copy_manifest.json in-place.
    Returns { task_id, status } immediately; the job runs in a background thread.
    """
    job_dir = _JOBS_DIR / task_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Task not found")

    # Locate required files
    as_pdf         = job_dir / "student_answersheet.pdf"
    grading_json   = job_dir / "grading_final.json"
    aligned_json   = job_dir / "aligned_answers.json"
    ocr_txt        = next(
        (job_dir / name for name in ("3_ocr_output.txt", "ocr_output.txt")
         if (job_dir / name).exists()),
        None
    )
    output_pdf     = job_dir / "checked_copy.pdf"
    manifest_path  = job_dir / "checked_copy_manifest.json"

    for required, label in [
        (as_pdf,       "student_answersheet.pdf"),
        (grading_json, "grading_final.json"),
        (aligned_json, "aligned_answers.json"),
    ]:
        if not required.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Required file not found in job directory: {label}"
            )

    # Build recheck command (reuses the same script entrypoint)
    cmd = [
        sys.executable,
        str(_BACKEND_DIR / "generate_checked_copy_v2.py"),
        "--pdf",      str(as_pdf),
        "--grading",  str(grading_json),
        "--aligned",  str(aligned_json),
        "--output",   str(output_pdf),
        "--manifest", str(manifest_path),
    ]
    if ocr_txt is not None:
        cmd += ["--ocr", str(ocr_txt)]

    # Mark status as running so the frontend can show a spinner
    result_file = job_dir / "result.json"
    def _update_status(data: dict):
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _run_recheck():
        _update_status({
            "status": "running",
            "stage": "recheck",
            "message": "Re-generating checked copy...",
            "progress": 90,
        })
        try:
            result = subprocess.run(cmd, cwd=str(_BACKEND_DIR), capture_output=True, text=True)
            if result.returncode != 0:
                _update_status({
                    "status": "failed",
                    "stage": "recheck_failed",
                    "message": "Recheck failed",
                    "error": result.stderr[-1000:],
                })
            else:
                # Restore the previous done state but signal recheck is complete
                prev = {}
                if result_file.exists():
                    try:
                        prev = json.loads(result_file.read_text())
                    except Exception:
                        pass
                _update_status({
                    **prev,
                    "status": "done",
                    "stage": "completed",
                    "message": "Grading Complete!",
                    "checked_copy_ready": True,
                })
        except Exception as e:
            _update_status({
                "status": "failed",
                "stage": "recheck_failed",
                "message": f"Recheck error: {e}",
            })

    t = threading.Thread(target=_run_recheck, daemon=True)
    t.start()

    return {"task_id": task_id, "status": "recheck_started"}


@router.post("/patch/{task_id}")
async def patch_pipeline_result(task_id: str, request: Request):
    """
    Apply mark / feedback corrections to a pipeline's checked copy.
    """
    job_dir = _JOBS_DIR / task_id
    manifest_path = job_dir / "checked_copy_manifest.json"
    
    if not manifest_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Annotation manifest not found. Please check this paper again to generate it."
        )
        
    import sys, os
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)
        
    try:
        from patch_checked_copy import apply_patch
        body = await request.json()
        corrections = body.get("corrections", {})
        
        patched_pdf_path = job_dir / "checked_copy_patched.pdf"
        
        apply_patch(
            manifest_path=str(manifest_path),
            corrections=corrections,
            output_path=str(patched_pdf_path)
        )
        
        return FileResponse(
            path=str(patched_pdf_path),
            filename="checked_copy_edited.pdf",
            media_type="application/pdf"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to apply patch: {e}")
