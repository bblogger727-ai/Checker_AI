"""
paddleocr_lock.py
=================
No-op stub — the cross-process file lock is no longer needed.

PaddleOCR now runs as a resident worker process (ocr_worker.py, port 9999)
that serialises OCR calls internally via an asyncio lock.
This module is kept so that the `with paddleocr_lock(...)` call site in
generate_checked_copy_v2.py continues to work without modification.
"""

from contextlib import contextmanager


@contextmanager
def paddleocr_lock(output_dir: str = None, timeout: float = 1800.0):
    """No-op context manager — OCR worker handles serialisation internally."""
    yield
