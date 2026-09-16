#!/bin/bash
# entrypoint.sh — starts OCR worker first, waits until ready, then starts main API

set -e

echo "=== [entrypoint] Starting OCR worker on port 9999 ==="
python /app/ocr_worker.py &
OCR_PID=$!

echo "=== [entrypoint] Waiting for OCR worker to load model (up to 120s) ==="
for i in $(seq 1 120); do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:9999/health || true)
    if [ "$STATUS" = "200" ]; then
        echo "=== [entrypoint] OCR worker ready after ${i}s ==="
        break
    fi
    sleep 1
done

if [ "$STATUS" != "200" ]; then
    echo "=== [entrypoint] WARNING: OCR worker did not become ready in 120s, starting main API anyway ==="
fi

echo "=== [entrypoint] Starting main API on port 8000 ==="
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
