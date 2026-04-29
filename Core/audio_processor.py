# ===========================================================
# SpeakSecure — Audio Processor
# Handles loading, resampling, and normalizing audio files.
# Used by EmbeddingService and AudioValidator.
# ===========================================================

import torch
import torchaudio

from constants import (
    TARGET_SAMPLE_RATE,
    MIN_AUDIO_DURATION_SECONDS,
    MAX_AUDIO_DURATION_SECONDS,
)

class AudioProcessor:
    """Low-level audio processing: load, resample, normalize."""

    def __init__(self):
        # Cache of Resample transforms keyed by source sample rate.
        # Creating a Resample object is relatively expensive (it pre-computes
        # the sinc filter kernel), so we reuse one instance per unique
        # source sample rate instead of rebuilding it on every call.
        self._resamplers: dict[int, torchaudio.transforms.Resample] = {}

    def load(self, file_path: str) -> tuple[torch.Tensor, int]:
        """Load audio file from disk and return waveform + sample rate."""
        try:
            waveform, sample_rate = torchaudio.load(file_path)
        except Exception as e:
            raise ValueError(f"Failed to load audio file: {e}")

        if waveform.numel() == 0:
            raise ValueError("Audio file is empty or corrupted.")

        return waveform, sample_rate

    def to_mono(self, waveform: torch.Tensor) -> torch.Tensor:
        """Convert multi-channel (stereo) audio to single-channel (mono)."""
        if waveform.shape[0] > 1:
            waveform = torch.mean(waveform, dim=0, keepdim=True)
        return waveform

    def resample(self, waveform: torch.Tensor, original_rate: int) -> torch.Tensor:
        """
        Resample audio to 16kHz target rate using torchaudio sinc interpolation.
        Resamplers are cached per source rate — torchaudio's Resample transform
        pre-computes its filter kernel at construction, so reusing one instance
        is faster than rebuilding it on every call.
        """
        if original_rate == TARGET_SAMPLE_RATE:
            return waveform

        resampler = self._resamplers.get(original_rate)
        if resampler is None:
            resampler = torchaudio.transforms.Resample(
                orig_freq=original_rate,
                new_freq=TARGET_SAMPLE_RATE,
            )
            self._resamplers[original_rate] = resampler

        return resampler(waveform)

    def normalize(self, waveform: torch.Tensor) -> torch.Tensor:
        """
        RMS normalization — stabilizes volume across different recordings.
        Uses a minimum RMS threshold to prevent amplification of near-silent
        audio (which would produce extreme values from tiny noise).
        """
        rms = torch.sqrt(torch.mean(waveform ** 2))
        # Require meaningful signal — below this threshold, leave audio as-is.
        # Very small RMS means mostly silence; dividing would amplify noise
        # to unrealistic levels and destabilize downstream models.
        MIN_RMS = 1e-4
        if rms > MIN_RMS:
            waveform = waveform / rms
        return waveform

    def validate_duration(self, waveform: torch.Tensor, sample_rate: int) -> None:
        """Reject audio that is too short or too long."""
        duration = waveform.shape[1] / sample_rate

        if duration < MIN_AUDIO_DURATION_SECONDS:
            raise ValueError(
                f"Audio too short ({duration:.1f}s). "
                f"Minimum is {MIN_AUDIO_DURATION_SECONDS}s."
            )

        if duration > MAX_AUDIO_DURATION_SECONDS:
            raise ValueError(
                f"Audio too long ({duration:.1f}s). "
                f"Maximum is {MAX_AUDIO_DURATION_SECONDS}s."
            )

    def process(self, file_path: str) -> torch.Tensor:
        """
        Full preprocessing pipeline:
        load → mono → resample to 16kHz → validate duration → RMS normalize.
        Used by ECAPA and VAD. NOT used by AASIST (needs raw audio).
        """
        waveform, sample_rate = self.load(file_path)
        waveform = self.to_mono(waveform)
        waveform = self.resample(waveform, sample_rate)
        self.validate_duration(waveform, TARGET_SAMPLE_RATE)
        waveform = self.normalize(waveform)
        return waveform