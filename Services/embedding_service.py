# ===========================================================
# SpeakSecure — Embedding Service
# Orchestrates the full pipeline from raw audio file
# to a clean, normalized voice embedding.
# Pipeline: AudioProcessor → VAD → VoiceEncoder (ECAPA-TDNN)
#
# AudioProcessor and VAD are injected so the entire app shares
# one instance of each (saves memory and load time).
# ===========================================================

import torch
import torch.nn.functional as F

from Core.audio_processor import AudioProcessor
from Core.vad import VoiceActivityDetector
from Core.voice_encoder import VoiceEncoder

class EmbeddingService:
    """Orchestrates the complete audio → voice embedding pipeline."""

    def __init__(
        self,
        audio_processor: AudioProcessor = None,
        vad: VoiceActivityDetector = None,
    ):
        # Use injected singletons when available; fall back to fresh
        # instances for backward compatibility (e.g. unit tests).
        self.audio_processor = audio_processor if audio_processor is not None else AudioProcessor()
        self.vad = vad if vad is not None else VoiceActivityDetector()
        self.encoder = VoiceEncoder()

    def extract_embedding(self, audio_path: str) -> torch.Tensor:
        """
        Full pipeline: load → preprocess → VAD → ECAPA embedding.
        Returns a 192-dimensional L2-normalized voice embedding.
        """
        # Step 1: Load, resample to 16kHz, RMS normalize
        waveform = self.audio_processor.process(audio_path)

        # Step 2: Remove silence, keep only speech segments
        waveform = self.vad.extract_speech(waveform)

        # Step 3: Extract speaker embedding via ECAPA-TDNN
        embedding = self.encoder.extract_embedding(waveform)

        return embedding

    def cosine_similarity(
        self,
        embedding_1: torch.Tensor,
        embedding_2: torch.Tensor,
    ) -> float:
        """
        Compute cosine similarity between two voice embeddings.
        Both embeddings are expected to be already L2-normalized
        (done by VoiceEncoder and VoiceprintRepository).
        Returns a float in [-1.0, 1.0] — higher means more similar.
        """
        score = F.cosine_similarity(
            embedding_1.unsqueeze(0),
            embedding_2.unsqueeze(0),
        )
        return float(score.item())