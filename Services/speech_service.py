# ===========================================================
# SpeakSecure — Speech Service
# Orchestrates speech-to-text transcription using Whisper.
# Used to verify that the user spoke the correct challenge digits.
# Whisper handles its own audio loading and resampling internally.
# ===========================================================

from Core.speech_recognizer import SpeechRecognizer

class SpeechService:
    """Manages speech-to-text operations for challenge verification."""

    def __init__(self):
        self.recognizer = SpeechRecognizer()

    def transcribe_audio(self, audio_path: str) -> dict:
        """
        Transcribe audio and return transcription + extracted digits.
        Thin wrapper around SpeechRecognizer — kept for symmetry with
        other services and to keep the service layer swappable.
        """
        return self.recognizer.transcribe(audio_path)