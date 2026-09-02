"""
paddleocr_lock.py
=================
Cross-process lock for PaddleOCR (Stage 7 - Checked Copy generation).
Ensures only ONE pipeline runs PaddleOCR at a time to prevent RAM exhaustion and OOM kills.
"""

import os
import sys
import time
import tempfile
import gc
from contextlib import contextmanager

LOCK_FILE = os.path.join(tempfile.gettempdir(), "checkerai_paddleocr_stage7.lock")


@contextmanager
def paddleocr_lock(output_dir: str = None, timeout: float = 1800.0):
    """
    Acquire cross-process lock for Stage 7.
    If another process is running Stage 7, waits until it finishes.
    Updates result.json in output_dir (if provided) so UI shows waiting status.
    """
    start_wait = time.time()
    status_updated = False

    def _notify_waiting():
        nonlocal status_updated
        if output_dir and os.path.isdir(output_dir):
            res_file = os.path.join(output_dir, "result.json")
            if os.path.exists(res_file):
                try:
                    import json
                    with open(res_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    data["stage"] = "stage_7"
                    data["message"] = "Waiting in queue: another paper is generating Checked Copy..."
                    with open(res_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                    status_updated = True
                except Exception:
                    pass

    def _notify_resumed():
        if output_dir and os.path.isdir(output_dir) and status_updated:
            res_file = os.path.join(output_dir, "result.json")
            if os.path.exists(res_file):
                try:
                    import json
                    with open(res_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    data["stage"] = "stage_7"
                    data["message"] = "Lock acquired. Generating checked copy (visual annotations)..."
                    with open(res_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                except Exception:
                    pass

    use_filelock = False
    try:
        from filelock import FileLock, Timeout
        use_filelock = True
    except ImportError:
        pass

    if use_filelock:
        lock = FileLock(LOCK_FILE)
        try:
            lock.acquire(timeout=0.2)
        except Timeout:
            print("\n" + "=" * 60, flush=True)
            print("  ⏳ [PaddleOCR Lock] Another pipeline is currently generating Checked Copy.", flush=True)
            print("  ⏳ Waiting in queue for Stage 7 lock to be released...", flush=True)
            print("=" * 60 + "\n", flush=True)
            _notify_waiting()
            lock.acquire(timeout=timeout)

        wait_duration = time.time() - start_wait
        if wait_duration > 0.5:
            print(f"  ✓ [PaddleOCR Lock] Acquired lock after waiting {wait_duration:.1f}s. Proceeding with Stage 7.", flush=True)
        _notify_resumed()

        try:
            yield
        finally:
            try:
                gc.collect()
            except Exception:
                pass
            try:
                lock.release()
            except Exception:
                pass
    else:
        # Fallback to fcntl on POSIX
        import fcntl
        with open(LOCK_FILE, "a+") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, IOError):
                print("\n" + "=" * 60, flush=True)
                print("  ⏳ [PaddleOCR Lock] Another pipeline is currently generating Checked Copy.", flush=True)
                print("  ⏳ Waiting in queue for Stage 7 lock to be released...", flush=True)
                print("=" * 60 + "\n", flush=True)
                _notify_waiting()
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

            wait_duration = time.time() - start_wait
            if wait_duration > 0.5:
                print(f"  ✓ [PaddleOCR Lock] Acquired lock after waiting {wait_duration:.1f}s. Proceeding with Stage 7.", flush=True)
            _notify_resumed()

            try:
                yield
            finally:
                try:
                    gc.collect()
                except Exception:
                    pass
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
