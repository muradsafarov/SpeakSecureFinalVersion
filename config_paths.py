# ===========================================================
# SpeakSecure — Path Configuration (torch-free)
#
# This module exists so that lightweight modules (Storage layer,
# unit tests for the rate limiter, etc.) can import the project's
# directory paths and database location WITHOUT pulling in torch
# as a transitive dependency.
#
# config.py imports from this file and adds device-specific things
# (DEVICE, COMPUTE_TYPE) which DO require torch. So:
#
#   - Anything that needs only paths → import from config_paths
#   - Anything that needs the device (model loaders, ML services)
#     → import from config (which re-exports paths AND adds device)
#
# This split keeps `pytest Tests/test_rate_limiter.py` runnable in
# environments where torch isn't installed (CI smoke tests, lint
# pipelines, contributor laptops without ML deps yet).
# ===========================================================

import os

# Fix OpenMP conflict between PyTorch and numpy on Windows.
# Set BEFORE importing anything that might pull torch transitively
# (this file is imported very early by Storage.database).
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

from pathlib import Path

# --- Base Directories ---
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "Data"
EMBEDDINGS_DIR = DATA_DIR / "Embeddings"     # Stored voice profiles
TEMP_AUDIO_DIR = DATA_DIR / "Temp_Audio"     # Temporary uploaded audio files
LOGS_DIR = DATA_DIR / "Logs"                 # Application log files

# Create all required directories on startup
for directory in [DATA_DIR, EMBEDDINGS_DIR, TEMP_AUDIO_DIR, LOGS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# --- Database ---
# SQLite file storing API keys and per-key usage counters.
# Keeping this in the Data/ directory means it's covered by .gitignore
# and backups along with the rest of the runtime state.
DATABASE_PATH = DATA_DIR / "speaksecure.db"