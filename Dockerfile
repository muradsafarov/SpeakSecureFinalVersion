# ===========================================================
# SpeakSecure — Hugging Face Spaces deployment
#
# HF Spaces with Docker SDK runs whatever this Dockerfile builds.
# Listens on port 7860 (HF default).
# ===========================================================

FROM python:3.11-slim

# System dependencies — ffmpeg required for audio decoding
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (cached layer — only re-runs if requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project
COPY . .

# HF Spaces always listens on port 7860
EXPOSE 7860

# Override the HOST/PORT from config.py via uvicorn command-line args
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]