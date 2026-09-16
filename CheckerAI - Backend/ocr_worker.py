"""
ocr_worker.py
=============
Persistent PaddleOCR worker — loaded ONCE at startup, serves all pipeline
requests via a tiny FastAPI on port 9999 (container-internal only).

Endpoints:
  GET  /health          → {"status": "ready"} once model is loaded
  POST /ocr             → accepts {"image_b64": "<base64 PNG>"}
                          returns {"lines": [...]}  (same schema as before)

This replaces the per-subprocess PaddleOCR instantiation in
generate_checked_copy_v2.py, removing the ~600 MB RAM spike on every paper.
"""

import os
import base64
import asyncio
import logging

import cv2
import numpy as np

# ── suppress PaddlePaddle noise ───────────────────────────────────────────────
os.environ["FLAGS_enable_pir_api"] = "0"
os.environ["FLAGS_use_mkldnn"]     = "0"
logging.getLogger("ppocr").setLevel(logging.ERROR)

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="CheckerAI OCR Worker", version="1.0")

# ── global model instance ─────────────────────────────────────────────────────
_ocr   = None
_ready = False

# Asyncio lock — ensures one OCR call at a time (PaddleOCR is not thread-safe)
_ocr_lock = asyncio.Lock()


@app.on_event("startup")
async def load_model():
    """Load PaddleOCR model at startup — runs once in the event loop."""
    global _ocr, _ready
    print("[OCR Worker] Loading PaddleOCR model...", flush=True)
    try:
        from paddleocr import PaddleOCR
        loop = asyncio.get_event_loop()
        _ocr = await loop.run_in_executor(
            None,
            lambda: PaddleOCR(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                lang="en",
                enable_mkldnn=False,
            ),
        )
        _ready = True
        print("[OCR Worker] PaddleOCR model loaded and ready.", flush=True)
    except Exception as e:
        print(f"[OCR Worker] Failed to load PaddleOCR: {e}", flush=True)
        _ready = False


# ── request / response models ─────────────────────────────────────────────────

class OcrRequest(BaseModel):
    image_b64: str   # base64-encoded PNG (from cv2.imencode)


class OcrLine(BaseModel):
    text:  str
    ymin:  float
    ymax:  float
    xmin:  float
    xmax:  float
    score: float


class OcrResponse(BaseModel):
    lines: list[OcrLine]


# ── endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    if _ready:
        return {"status": "ready"}
    from fastapi.responses import JSONResponse
    return JSONResponse({"status": "loading"}, status_code=503)


@app.post("/ocr", response_model=OcrResponse)
async def ocr_endpoint(req: OcrRequest):
    if not _ready or _ocr is None:
        raise HTTPException(status_code=503, detail="OCR model not ready yet")

    # Decode base64 PNG -> numpy BGR image
    try:
        img_bytes = base64.b64decode(req.image_b64)
        img_np    = cv2.imdecode(
            np.frombuffer(img_bytes, dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        if img_np is None:
            raise ValueError("cv2.imdecode returned None")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Image decode error: {e}")

    h, w = img_np.shape[:2]

    async with _ocr_lock:
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, lambda: _ocr.ocr(img_np))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"OCR prediction error: {e}")

    if not result:
        return OcrResponse(lines=[])

    lines = []
    for item in result:
        rec_texts  = item.get("rec_texts",  [])
        rec_boxes  = item.get("rec_boxes",  [])
        rec_scores = item.get("rec_scores", [])
        for text, box, score in zip(rec_texts, rec_boxes, rec_scores):
            box = np.array(box)
            if box.ndim == 1:
                xmin, ymin, xmax, ymax = box
            else:
                xmin, ymin = box.min(axis=0)
                xmax, ymax = box.max(axis=0)
            lines.append(OcrLine(
                text  = str(text),
                ymin  = max(0.0, float(ymin) / h),
                ymax  = min(1.0, float(ymax) / h),
                xmin  = max(0.0, float(xmin) / w),
                xmax  = min(1.0, float(xmax) / w),
                score = float(score),
            ))

    lines.sort(key=lambda l: l.ymin)
    return OcrResponse(lines=lines)


# ── entrypoint ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9999, log_level="warning")
