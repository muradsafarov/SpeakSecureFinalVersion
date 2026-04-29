# ===========================================================
# SpeakSecure — Status Route
# GET /status — Returns system info and configuration.
# Useful for debugging and demo presentations.
# ===========================================================

from fastapi import APIRouter

from config import DEVICE, WHISPER_MODEL_SIZE, ECAPA_MODEL_SOURCE
from constants import (
    API_VERSION,
    SIMILARITY_THRESHOLD,
    BORDERLINE_THRESHOLD,
    CHALLENGE_LENGTH,
    CHALLENGE_EXPIRATION_SECONDS,
    MAX_FAILED_ATTEMPTS,
    LOCKOUT_DURATION_SECONDS,
    MAX_SAMPLES_PER_USER,
    SPOOF_CONFIDENCE_THRESHOLD_ENROL,
    SPOOF_CONFIDENCE_THRESHOLD_VERIFY,
)

router = APIRouter(tags=["Status"])

@router.get("/status")
def system_status():
    """
    Returns full system configuration and model information.
    Useful for debugging, monitoring, and demo presentations.
    Shows which models are loaded, thresholds, and security settings.
    """
    return {
        "version": API_VERSION,
        "device": DEVICE,
        "models": {
            "voice_encoder": ECAPA_MODEL_SOURCE,
            "speech_recognizer": f"faster-whisper ({WHISPER_MODEL_SIZE})",
            "vad": "silero-vad",
            # AASIST pretrained model for TTS/deepfake detection
            "anti_spoof": "AASIST (Graph Attention Networks)",
        },
        "thresholds": {
            "similarity": SIMILARITY_THRESHOLD,
            "borderline": BORDERLINE_THRESHOLD,
            "spoof_enrol_strict": SPOOF_CONFIDENCE_THRESHOLD_ENROL,
            "spoof_verify_lenient": SPOOF_CONFIDENCE_THRESHOLD_VERIFY,
        },
        "challenge": {
            "length": CHALLENGE_LENGTH,
            "expiration_seconds": CHALLENGE_EXPIRATION_SECONDS,
        },
        "enrolment": {
            "max_samples_per_user": MAX_SAMPLES_PER_USER,
        },
        "security": {
            "max_failed_attempts": MAX_FAILED_ATTEMPTS,
            "lockout_duration_seconds": LOCKOUT_DURATION_SECONDS,
        },
    }