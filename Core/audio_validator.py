# ===========================================================
# SpeakSecure — Audio Validator
# Validates that audio contains real human speech.
# Rejects: noise, music, animal sounds, silence.
#
# Two checks (transcription moved to service layer to avoid duplication):
# 1. Speech ratio — enough of the audio must be speech (VAD)
# 2. Speech energy — speech segments must be loud enough
#
# Stricter for enrolment than for verification.
# ===========================================================

import torch
from loguru import logger

from Core.vad import VoiceActivityDetector

# Thresholds are defined in constants.py — single source of truth across
# the codebase. Imported below to avoid drift between this validator and
# any other file that needs to reason about speech ratios / energy.
from constants import (
    ENROL_MIN_SPEECH_RATIO,
    VERIFY_MIN_SPEECH_RATIO,
    MIN_SPEECH_ENERGY,
)

class AudioValidator:
    """
    Validates that audio contains genuine human speech.
    Two modes: 'enrolment' (strict) and 'verification' (relaxed).
    Note: Transcription check is done in the service layer to avoid
    running Whisper twice (once here and once for challenge digits).

    The VAD is injected so that the entire app can share a single
    Silero model instance (saves memory and load time).
    """

    def __init__(self, vad: VoiceActivityDetector = None):
        # Allow the caller to inject a shared VAD; fall back to a fresh
        # instance for backward compatibility (e.g. unit tests that
        # construct AudioValidator() directly).
        self.vad = vad if vad is not None else VoiceActivityDetector()

    def validate(
        self,
        waveform: torch.Tensor,
        mode: str = "enrolment",
    ) -> dict:
        """
        Run validation checks on the audio.
        Raises ValueError if any check fails.
        """
        if mode == "enrolment":
            min_speech_ratio = ENROL_MIN_SPEECH_RATIO
        else:
            min_speech_ratio = VERIFY_MIN_SPEECH_RATIO

        checks = {}

        # --- Check 1: Speech Ratio (VAD) ---
        # Measures what percentage of the audio contains speech
        speech_ratio = self.vad.get_speech_ratio(waveform)
        ratio_passed = speech_ratio >= min_speech_ratio

        checks["speech_ratio"] = {
            "passed": ratio_passed,
            "value": round(speech_ratio, 4),
            "threshold": min_speech_ratio,
        }

        if not ratio_passed:
            logger.warning(f"Audio rejected: speech ratio {speech_ratio:.0%} below {min_speech_ratio:.0%}")
            raise ValueError(
                f"Audio rejected: insufficient speech detected "
                f"({speech_ratio:.0%} speech, minimum {min_speech_ratio:.0%}). "
                f"Please speak clearly for the entire recording."
            )

        # --- Check 2: Speech Energy ---
        # Ensures speech segments are loud enough (not whispered/distant)
        speech_segments = self.vad.extract_speech(waveform)
        rms_energy = torch.sqrt(torch.mean(speech_segments ** 2)).item()
        energy_passed = rms_energy >= MIN_SPEECH_ENERGY

        checks["speech_energy"] = {
            "passed": energy_passed,
            "value": round(rms_energy, 6),
            "threshold": MIN_SPEECH_ENERGY,
        }

        if not energy_passed:
            logger.warning(f"Audio rejected: speech energy {rms_energy:.6f} below {MIN_SPEECH_ENERGY}")
            raise ValueError(
                "Audio rejected: speech is too quiet. "
                "Please speak louder or move closer to the microphone."
            )

        return {
            "is_valid": True,
            "checks": checks,
            "message": "Audio validated: human speech confirmed.",
        }