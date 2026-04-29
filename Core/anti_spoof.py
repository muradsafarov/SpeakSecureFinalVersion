# ===========================================================
# SpeakSecure — Anti-Spoofing (AASIST)
# Detects spoofed audio (TTS, deepfake, replay) using the
# AASIST pretrained model (Graph Attention Networks).
# Paper: "AASIST: Audio Anti-Spoofing using Integrated
#         Spectro-Temporal Graph Attention Networks"
#
# The threshold is passed per-call so that enrolment and
# verification can use different sensitivity levels:
#   - Enrolment: strict (low threshold) to keep voice profiles clean
#   - Verification: lenient (high threshold) to avoid false rejections
# ===========================================================

import torch
import torch.nn.functional as F
from pathlib import Path

from config import DEVICE
from constants import SPOOF_CONFIDENCE_THRESHOLD_ENROL

# AASIST model expects exactly 64600 samples (~4.03s at 16kHz)
AASIST_INPUT_LENGTH = 64600

class AntiSpoof:
    """
    Detects spoofed audio using the pretrained AASIST model.
    Classifies audio as bonafide (real human) or spoof (TTS/deepfake).
    """

    def __init__(self):
        self.model = None
        # Path to AASIST model architecture and pretrained weights
        self.model_dir = Path(__file__).resolve().parent / "AASIST"

    def _get_model(self):
        """Lazy-load AASIST model with pretrained weights."""
        if self.model is None:
            from Core.AASIST.aasist_model import Model

            # Official AASIST architecture config from the paper
            model_config = {
                "filts": [70, [1, 32], [32, 32], [32, 64], [64, 64]],
                "gat_dims": [64, 32],
                "pool_ratios": [0.5, 0.7, 0.5, 0.5],
                "temperatures": [2.0, 2.0, 100.0, 100.0],
                "first_conv": 128,
            }

            self.model = Model(model_config)

            weights_path = self.model_dir / "AASIST.pth"

            if not weights_path.exists():
                raise FileNotFoundError(
                    f"AASIST weights not found at {weights_path}. "
                    f"Download from: https://github.com/clovaai/aasist"
                )

            # Load pretrained weights trained on ASVspoof 2019 LA dataset
            self.model.load_state_dict(
                torch.load(weights_path, map_location=DEVICE, weights_only=True)
            )
            self.model = self.model.to(DEVICE)
            self.model.eval()

        return self.model

    def _prepare_input(self, waveform: torch.Tensor) -> torch.Tensor:
        """
        Pad or truncate audio to exactly 64600 samples for AASIST.
        Short audio is zero-padded, long audio is truncated.
        """
        # AASIST expects 1D input
        if waveform.dim() == 2:
            waveform = waveform.squeeze(0)

        length = waveform.shape[0]

        if length < AASIST_INPUT_LENGTH:
            # Pad with zeros to reach required length
            waveform = F.pad(waveform, (0, AASIST_INPUT_LENGTH - length))
        elif length > AASIST_INPUT_LENGTH:
            # Truncate to required length
            waveform = waveform[:AASIST_INPUT_LENGTH]

        # Add batch dimension: (1, 64600)
        return waveform.unsqueeze(0)

    def analyze(self, waveform: torch.Tensor, threshold: float = None) -> dict:
        """
        Analyze audio for spoofing using AASIST.

        AASIST output shape: (batch, 2)
            index 0 = spoof score
            index 1 = bonafide score

        Args:
            waveform: Raw mono audio tensor (no RMS normalization).
            threshold: Spoof probability threshold. If None, falls back to
                the strict enrolment default. Pass an explicit value (e.g.
                SPOOF_CONFIDENCE_THRESHOLD_VERIFY) to be lenient.

        Returns:
            dict with keys:
              - spoof_detected: bool, True if spoof probability >= threshold
              - confidence:     float, the spoof probability in [0, 1]
              - label:          "spoof" or "bonafide"
              - threshold_used: the threshold applied (for logging/debug)
        """
        # Fall back to strict enrolment threshold if none specified
        if threshold is None:
            threshold = SPOOF_CONFIDENCE_THRESHOLD_ENROL

        model = self._get_model()
        audio_input = self._prepare_input(waveform).to(DEVICE)

        # Run inference with no gradient computation
        with torch.no_grad():
            _, output = model(audio_input)

        # Convert logits to probabilities; index 0 = spoof, index 1 = bonafide
        # (the two values sum to 1.0, so we only need one of them).
        probabilities = torch.softmax(output, dim=1)
        spoof_prob = probabilities[0][0].item()

        # Compare spoof probability against the caller-supplied threshold
        spoof_detected = spoof_prob >= threshold
        label = "spoof" if spoof_detected else "bonafide"

        return {
            "spoof_detected": spoof_detected,
            "confidence": round(spoof_prob, 4),
            "label": label,
            "threshold_used": threshold,
        }