# ===========================================================
# SpeakSecure — Spoofing Service
# Orchestrates anti-spoofing analysis using AASIST model.
# IMPORTANT: AASIST expects raw audio without RMS normalization.
# The service loads audio separately from the main pipeline
# to preserve original spectral characteristics.
#
# The caller passes a `threshold` so that enrolment (strict) and
# verification (lenient) can use different sensitivity levels.
# ===========================================================

import torch
import torchaudio

from Core.anti_spoof import AntiSpoof
from constants import TARGET_SAMPLE_RATE

class SpoofingService:
    """Manages spoofing detection using AASIST pretrained model."""

    def __init__(self):
        self.anti_spoof = AntiSpoof()

    def _load_raw_audio(self, audio_path: str) -> torch.Tensor:
        """
        Load audio as raw waveform — mono, 16kHz, NO normalization.
        AASIST was trained on raw audio; RMS normalization would
        distort the spectral features it relies on for detection.
        """
        waveform, sample_rate = torchaudio.load(audio_path)

        # Convert stereo to mono if needed
        if waveform.shape[0] > 1:
            waveform = torch.mean(waveform, dim=0, keepdim=True)

        # Resample to 16kHz using torchaudio (high-quality sinc interpolation)
        if sample_rate != TARGET_SAMPLE_RATE:
            resampler = torchaudio.transforms.Resample(
                orig_freq=sample_rate,
                new_freq=TARGET_SAMPLE_RATE,
            )
            waveform = resampler(waveform)

        return waveform

    def analyze_audio(self, audio_path: str, threshold: float = None) -> dict:
        """
        Run AASIST anti-spoofing analysis on an audio file.
        Detects TTS-generated and deepfake voices.

        Args:
            audio_path: Path to the audio file on disk.
            threshold: Spoof probability cutoff. If None, the strict
                enrolment default is used. Pass SPOOF_CONFIDENCE_THRESHOLD_VERIFY
                for a lenient check during sign-in.

        Returns:
            dict with keys: spoof_detected, confidence, label, threshold_used.
        """
        # Load raw audio (separate from ECAPA pipeline — no normalization)
        waveform = self._load_raw_audio(audio_path)
        return self.anti_spoof.analyze(waveform, threshold=threshold)