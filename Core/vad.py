# ===========================================================
# SpeakSecure — Voice Activity Detection (VAD)
# Filters out silence and background noise using Silero VAD.
# Only keeps segments where human speech is detected.
# Used in: EmbeddingService pipeline, AudioValidator checks.
# ===========================================================

import torch
from silero_vad import load_silero_vad, get_speech_timestamps

from constants import TARGET_SAMPLE_RATE

class VoiceActivityDetector:
    """Detects and extracts speech segments from audio."""

    def __init__(self):
        self.model = None

    def _get_model(self):
        """Lazy-load Silero VAD model (runs on CPU, ~2MB)."""
        if self.model is None:
            self.model = load_silero_vad()
        return self.model

    def detect_speech(self, waveform: torch.Tensor) -> list[dict]:
        """
        Detect speech timestamps in the waveform.

        Args:
            waveform: Mono audio tensor, shape (1, samples) or (samples,).

        Returns:
            List of dicts with 'start' and 'end' sample indices.
        """
        model = self._get_model()

        # Silero VAD expects 1D tensor
        if waveform.dim() == 2:
            wav = waveform.squeeze(0)
        else:
            wav = waveform

        # Get speech segments with configurable sensitivity
        timestamps = get_speech_timestamps(
            wav,
            model,
            sampling_rate=TARGET_SAMPLE_RATE,
            threshold=0.5,                  # Speech detection confidence
            min_speech_duration_ms=250,     # Ignore speech shorter than 250ms
            min_silence_duration_ms=100,    # Merge segments separated by < 100ms
        )

        return timestamps

    def extract_speech(self, waveform: torch.Tensor) -> torch.Tensor:
        """
        Extract only speech segments, removing silence and noise.
        Concatenates all speech portions into a single tensor.

        Raises:
            ValueError: If no speech is detected at all.
        """
        timestamps = self.detect_speech(waveform)

        if not timestamps:
            raise ValueError(
                "No speech detected in the audio. "
                "Please speak clearly and try again."
            )

        # Ensure waveform is 2D for slicing
        if waveform.dim() == 1:
            waveform = waveform.unsqueeze(0)

        # Concatenate all detected speech segments
        speech_segments = []
        for ts in timestamps:
            segment = waveform[:, ts["start"]:ts["end"]]
            speech_segments.append(segment)

        speech_only = torch.cat(speech_segments, dim=1)

        return speech_only

    def get_speech_ratio(self, waveform: torch.Tensor) -> float:
        """
        Calculate percentage of audio that contains speech.
        Returns value between 0.0 (no speech) and 1.0 (all speech).
        Used by AudioValidator to reject non-speech audio.
        """
        timestamps = self.detect_speech(waveform)

        if waveform.dim() == 2:
            total_samples = waveform.shape[1]
        else:
            total_samples = waveform.shape[0]

        if total_samples == 0:
            return 0.0

        speech_samples = sum(ts["end"] - ts["start"] for ts in timestamps)
        return speech_samples / total_samples