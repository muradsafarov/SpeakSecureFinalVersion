# ===========================================================
# SpeakSecure — Audio Processor Tests
# Unit tests for low-level audio processing functions.
# Uses synthetic (random) tensors — no real audio files needed.
# ===========================================================

import pytest
import torch

from Core.audio_processor import AudioProcessor
from constants import TARGET_SAMPLE_RATE

@pytest.fixture
def processor():
    return AudioProcessor()

class TestToMono:
    """Tests for stereo to mono conversion."""

    def test_stereo_to_mono(self, processor):
        # 2-channel audio should be averaged into 1 channel
        stereo = torch.randn(2, 16000)
        mono = processor.to_mono(stereo)
        assert mono.shape[0] == 1

    def test_mono_stays_mono(self, processor):
        # Already mono audio should pass through unchanged
        mono = torch.randn(1, 16000)
        result = processor.to_mono(mono)
        assert result.shape[0] == 1

class TestResample:
    """Tests for sample rate conversion."""

    def test_resample_from_44100(self, processor):
        # 1 second of audio at 44.1kHz should resample to ~16k samples
        waveform = torch.randn(1, 44100)
        result = processor.resample(waveform, 44100)
        # Allow a small tolerance for sinc interpolation rounding
        assert abs(result.shape[1] - TARGET_SAMPLE_RATE) < 10

    def test_no_resample_if_correct_rate(self, processor):
        # Audio already at 16kHz should not be modified
        waveform = torch.randn(1, 16000)
        result = processor.resample(waveform, TARGET_SAMPLE_RATE)
        assert result.shape[1] == 16000

class TestNormalize:
    """Tests for RMS normalization."""

    def test_normalize_nonzero(self, processor):
        # After normalization, RMS should be approximately 1.0
        waveform = torch.randn(1, 16000) * 0.5
        result = processor.normalize(waveform)
        rms = torch.sqrt(torch.mean(result ** 2))
        assert abs(rms.item() - 1.0) < 0.01

    def test_normalize_silence(self, processor):
        # Silent audio (all zeros) should remain silent after normalization
        silence = torch.zeros(1, 16000)
        result = processor.normalize(silence)
        assert torch.all(result == 0)

class TestValidateDuration:
    """Tests for audio duration validation."""

    def test_valid_duration(self, processor):
        # 3 seconds — within acceptable range, should not raise
        waveform = torch.randn(1, int(3.0 * TARGET_SAMPLE_RATE))
        processor.validate_duration(waveform, TARGET_SAMPLE_RATE)

    def test_too_short(self, processor):
        # 0.5 seconds — below minimum, should raise ValueError
        short = torch.randn(1, int(0.5 * TARGET_SAMPLE_RATE))
        with pytest.raises(ValueError, match="too short"):
            processor.validate_duration(short, TARGET_SAMPLE_RATE)

    def test_too_long(self, processor):
        # 20 seconds — above maximum, should raise ValueError
        long = torch.randn(1, int(20.0 * TARGET_SAMPLE_RATE))
        with pytest.raises(ValueError, match="too long"):
            processor.validate_duration(long, TARGET_SAMPLE_RATE)