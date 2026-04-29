# ===========================================================
# SpeakSecure — Model Loader
# Eagerly loads all ML models on server startup with retry logic.
# Prevents first-request failures due to network issues or
# temporary HuggingFace unavailability.
# ===========================================================

import time
from loguru import logger

from Services.dependencies import (
    embedding_service,
    speech_service,
    spoofing_service,
)

class ModelLoader:
    """Loads all ML models on startup with retry logic."""

    def __init__(self, max_retries: int = 3, retry_delay_seconds: int = 5):
        self.max_retries = max_retries
        self.retry_delay = retry_delay_seconds

    def load_all(self) -> None:
        """
        Load all ML models eagerly.
        Raises RuntimeError if any model fails after max_retries.
        """
        logger.info("Loading ML models on startup...")

        # Each tuple: (model_name, load_function)
        models = [
            ("ECAPA-TDNN (voice encoder)", self._load_ecapa),
            ("Silero VAD", self._load_vad),
            ("Whisper (speech recognition)", self._load_whisper),
            ("AASIST (anti-spoofing)", self._load_aasist),
        ]

        for name, loader in models:
            self._load_with_retry(name, loader)

        logger.info("All ML models loaded successfully")

    def _load_with_retry(self, name: str, loader_fn) -> None:
        """Try to load a model up to max_retries times."""
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(f"Loading {name} (attempt {attempt}/{self.max_retries})...")
                loader_fn()
                logger.info(f"{name} loaded")
                return
            except Exception as e:
                logger.warning(f"Failed to load {name} on attempt {attempt}: {e}")
                if attempt < self.max_retries:
                    logger.info(f"Retrying in {self.retry_delay}s...")
                    time.sleep(self.retry_delay)
                else:
                    # Final attempt failed — raise to prevent server startup
                    raise RuntimeError(
                        f"Failed to load {name} after {self.max_retries} attempts. "
                        f"Last error: {e}"
                    )

    def _load_ecapa(self) -> None:
        """Trigger ECAPA-TDNN lazy loading."""
        embedding_service.encoder._get_classifier()

    def _load_vad(self) -> None:
        """Trigger Silero VAD lazy loading."""
        embedding_service.vad._get_model()

    def _load_whisper(self) -> None:
        """Trigger Whisper lazy loading."""
        speech_service.recognizer._get_model()

    def _load_aasist(self) -> None:
        """Trigger AASIST lazy loading."""
        spoofing_service.anti_spoof._get_model()