"""
SubtitlesAI Backend — FastAPI service.
Accepts video uploads, queues subtitle generation via VideoToSRTConverter,
returns SRT for download. Serves its own HTML frontend at GET /.
"""

import os
import sys
import uuid
import json
import time
import shutil
import threading
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import subprocess

JOBS_DIR = Path("/subtitles_jobs")
JOBS_DIR.mkdir(parents=True, exist_ok=True)
MAX_FILE_SIZE = 500 * 1024 * 1024
_semaphore = threading.Semaphore(2)
_tasks: dict = {}

app = FastAPI(title="SubtitlesAI", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _write_status(job_dir: Path, status: str, message: str, extra: dict = None):
    data = {"status": status, "message": message, "ts": time.time()}
    if extra:
        data.update(extra)
    (job_dir / "status.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def _run_job(job_id, video_path, language, splits, word_replacements):
    job_dir = JOBS_DIR / job_id
    output_srt = str(job_dir / "subtitles.srt")
    _tasks[job_id]["status"] = "processing"
    _write_status(job_dir, "processing", f"Extracting audio and transcribing ({splits} splits)...")
    try:
        script = Path(__file__).parent / "subtitles_ai.py"
        cmd = [sys.executable, str(script), video_path, "-o", output_srt,
               "--language", language, "--splits", str(splits)]
        if word_replacements:
            for old, new in word_replacements.items():
                cmd += ["--replace", f"{old}:{new}"]
        env = os.environ.copy()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, env=env)
        if result.returncode != 0:
            raise RuntimeError(result.stderr[-2000:] or "Script failed")
        if not Path(output_srt).exists():
            raise RuntimeError("SRT file was not created")
        _tasks[job_id]["status"] = "done"
        _write_status(job_dir, "done", "Subtitles ready!", extra={"srt_path": output_srt})
    except subprocess.TimeoutExpired:
        _tasks[job_id]["status"] = "failed"
        _write_status(job_dir, "failed", "Job timed out after 60 minutes.")
    except Exception as e:
        _tasks[job_id]["status"] = "failed"
        _write_status(job_dir, "failed", f"Error: {str(e)[:500]}")
    finally:
        try:
            if os.path.exists(video_path):
                os.remove(video_path)
        except Exception:
            pass


def _queue_job(job_id, video_path, language, splits, word_replacements):
    _tasks[job_id]["status"] = "queued"
    _write_status(JOBS_DIR / job_id, "queued", "Waiting for an available slot...")
    with _semaphore:
        _run_job(job_id, video_path, language, splits, word_replacements)


FRONTEND_HTML = open(Path(__file__).parent / "index.html").read()


@app.get("/", response_class=HTMLResponse)
async def frontend():
    return HTMLResponse(content=FRONTEND_HTML)


@app.post("/upload")
async def upload_video(
    video: UploadFile = File(...),
    language: str = Form("hi"),
    splits: int = Form(3),
    word_replacements: str = Form("{}"),
):
    try:
        repl = json.loads(word_replacements)
        if not isinstance(repl, dict):
            repl = {}
    except Exception:
        repl = {}

    job_id = uuid.uuid4().hex
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    video_path = str(job_dir / f"input_{video.filename}")
    written = 0
    with open(video_path, "wb") as f:
        while True:
            chunk = await video.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_FILE_SIZE:
                f.close()
                shutil.rmtree(job_dir, ignore_errors=True)
                raise HTTPException(status_code=413, detail="File exceeds 500 MB limit")
            f.write(chunk)

    _tasks[job_id] = {
        "job_id": job_id, "status": "queued", "filename": video.filename,
        "language": language, "splits": splits, "created_at": time.time(),
    }
    _write_status(job_dir, "queued", "Queued...")

    t = threading.Thread(target=_queue_job,
                         args=(job_id, video_path, language, splits, repl or None),
                         daemon=True)
    t.start()
    return JSONResponse({"job_id": job_id, "status": "queued"})


@app.get("/status/{job_id}")
def get_status(job_id: str):
    status_file = JOBS_DIR / job_id / "status.json"
    if not status_file.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse(json.loads(status_file.read_text()))


@app.get("/download/{job_id}")
def download_srt(job_id: str):
    srt_path = JOBS_DIR / job_id / "subtitles.srt"
    if not srt_path.exists():
        raise HTTPException(status_code=404, detail="SRT not ready")
    task = _tasks.get(job_id, {})
    orig = Path(task.get("filename", "video")).stem
    return FileResponse(path=str(srt_path), media_type="text/plain", filename=f"{orig}.srt")


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
