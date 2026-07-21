#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# CheckerAI — Start Both Servers
# ─────────────────────────────────────────────────────────────────────────────
# Usage: ./start.sh
#   Starts the FastAPI backend (port 8000) and the Vite frontend (port 5173)
#   in parallel. Press Ctrl+C to stop both.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/CheckerAI - Backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
VENV_PYTHON="$BACKEND_DIR/venv/bin/python"
VENV_UVICORN="$BACKEND_DIR/venv/bin/uvicorn"

echo "=========================================="
echo "  CheckerAI — Starting All Services"
echo "=========================================="

# ── Verify backend venv exists ─────────────────────────────────────────────
if [ ! -f "$VENV_PYTHON" ]; then
  echo "ERROR: Python venv not found at $BACKEND_DIR/venv"
  echo "Run:  cd \"$BACKEND_DIR\" && python3 -m venv venv && venv/bin/pip install -r requirements.txt"
  exit 1
fi

# ── Verify frontend node_modules ──────────────────────────────────────────
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  echo "Installing frontend dependencies..."
  cd "$FRONTEND_DIR" && npm install
fi

# ── Create pipeline_jobs dir (needed by pipelines.py) ────────────────────
mkdir -p "$BACKEND_DIR/pipeline_jobs"

# ── Trap to kill all child processes on Ctrl+C ───────────────────────────
trap 'echo "\nStopping all services..."; kill 0' EXIT INT TERM

echo ""
echo "  Backend  →  http://localhost:8000"
echo "  Frontend →  http://localhost:5173"
echo "  API Docs →  http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop."
echo "=========================================="

# ── Start FastAPI backend ─────────────────────────────────────────────────
(
  cd "$BACKEND_DIR"
  export PYTHONPATH="$BACKEND_DIR:$(dirname "$BACKEND_DIR")/CA_Feedback_Pipeline"
  "$VENV_UVICORN" app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --reload \
    --reload-dir app \
    2>&1 | sed 's/^/[BACKEND] /'
) &
BACKEND_PID=$!

# ── Start Vite frontend ───────────────────────────────────────────────────
(
  cd "$FRONTEND_DIR"
  npm run dev 2>&1 | sed 's/^/[FRONTEND] /'
) &
FRONTEND_PID=$!

echo "[INFO] Backend PID=$BACKEND_PID  Frontend PID=$FRONTEND_PID"

# Wait for both
wait $BACKEND_PID $FRONTEND_PID
