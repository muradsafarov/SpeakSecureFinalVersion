# ===========================================================
# SpeakSecure — Configuration
# Runtime settings: paths, device selection, model options.
#
# Path constants live in config_paths.py (torch-free) so that
# lightweight modules — the Storage layer, unit tests for the
# rate limiter — can import them without pulling torch as a
# transitive dependency. This file re-exports them for backward
# compatibility and adds the device-specific settings (DEVICE,
# COMPUTE_TYPE) which DO require torch.
# ===========================================================

# Re-export all path constants. KMP_DUPLICATE_LIB_OK is also set
# inside config_paths so it's already in place by the time we
# import torch below.
from config_paths import (
    BASE_DIR,
    DATA_DIR,
    EMBEDDINGS_DIR,
    TEMP_AUDIO_DIR,
    LOGS_DIR,
    DATABASE_PATH,
)

# Mark these as intentional re-exports (suppresses 'imported but unused'
# warnings in linters — these names are part of this module's public API
# even though we don't use them inside this file).
__all__ = [
    "BASE_DIR",
    "DATA_DIR",
    "EMBEDDINGS_DIR",
    "TEMP_AUDIO_DIR",
    "LOGS_DIR",
    "DATABASE_PATH",
    "DEVICE",
    "COMPUTE_TYPE",
    "ECAPA_MODEL_SOURCE",
    "WHISPER_MODEL_SIZE",
    "HOST",
    "PORT",
]

import torch

# --- Device Selection ---
# Automatically use GPU if available, otherwise fall back to CPU
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
COMPUTE_TYPE = "float16" if DEVICE == "cuda" else "int8"

# --- Model Settings ---
ECAPA_MODEL_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"  # Voice embedding model
WHISPER_MODEL_SIZE = "small"                               # Speech recognition model

# --- Server ---
HOST = "0.0.0.0"
PORT = 8000