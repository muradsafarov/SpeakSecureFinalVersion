# ===========================================================
# SpeakSecure — Voice Encoder
# Extracts voice embeddings using ECAPA-TDNN (SpeechBrain).
# Each voice is converted to a 192-dimensional vector
# that uniquely represents the speaker's identity.
# ===========================================================

import torch
import torch.nn.functional as F
from speechbrain.inference.speaker import EncoderClassifier

from config import ECAPA_MODEL_SOURCE, DEVICE

class VoiceEncoder:
    """Extracts speaker embeddings using ECAPA-TDNN."""

    def __init__(self):
        self.classifier = None

    def _get_classifier(self) -> EncoderClassifier:
        """Lazy-load ECAPA-TDNN model from HuggingFace."""
        if self.classifier is None:
            self.classifier = EncoderClassifier.from_hparams(
                source=ECAPA_MODEL_SOURCE,
                run_opts={"device": DEVICE},
            )
        return self.classifier

    def extract_embedding(self, waveform: torch.Tensor) -> torch.Tensor:
        """
        Extract a normalized speaker embedding from preprocessed audio.
        Input must be 16kHz mono, RMS-normalized, VAD-filtered.

        Args:
            waveform: Preprocessed mono audio tensor, shape (1, samples).

        Returns:
            L2-normalized embedding tensor, shape (192,).
        """
        classifier = self._get_classifier()

        # ECAPA expects shape (batch, samples)
        if waveform.dim() == 1:
            waveform = waveform.unsqueeze(0)

        # Extract raw embedding from ECAPA-TDNN
        embedding = classifier.encode_batch(waveform)

        if embedding is None:
            raise ValueError("Failed to extract embedding from audio.")

        # Squeeze to 1D and L2-normalize for cosine similarity comparison
        embedding = embedding.squeeze().detach().cpu()
        embedding = F.normalize(embedding, p=2, dim=0)

        return embedding