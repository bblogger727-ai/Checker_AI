# CheckerAI Backend - Dockerfile
# Python FastAPI with OCR dependencies

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for PDF processing and PaddleOCR/OpenCV
RUN apt-get update && apt-get install -y \
    poppler-utils \
    tesseract-ocr \
    libpq-dev \
    gcc \
    g++ \
    libgomp1 \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create upload directories
RUN mkdir -p uploads/exams uploads/students uploads/results data

# Make entrypoint executable
RUN chmod +x /app/entrypoint.sh

# Expose port
EXPOSE 8000

# Start OCR worker (port 9999, internal) then main API (port 8000)
CMD ["/app/entrypoint.sh"]
