# ===========================================================
# SpeakSecure — Speech Recognizer
# Transcribes spoken digits using Faster-Whisper.
# Handles both numeric ("738") and word ("seven three eight")
# representations of digits in the transcription.
# Filters out known Whisper hallucinations on silent audio.
# ===========================================================

import re
from faster_whisper import WhisperModel

from config import WHISPER_MODEL_SIZE, DEVICE, COMPUTE_TYPE

# Word-to-digit mapping for multiple languages
WORD_TO_DIGIT = {
    # English
    "zero": "0", "one": "1", "two": "2", "three": "3",
    "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9",
    # Common Whisper misrecognitions
    "to": "2", "too": "2", "for": "4", "fore": "4",
    "won": "1", "ate": "8",
}

# Known Whisper hallucinations on silent/empty audio
# Whisper is trained on YouTube subtitles and outputs these phrases
# when it has nothing meaningful to transcribe.
WHISPER_HALLUCINATIONS = {
    "thanks for watching",
    "thanks for watching!",
    "thank you for watching",
    "thank you for watching.",
    "thank you.",
    "thank you",
    "thanks.",
    "thanks",
    "please subscribe",
    "please subscribe.",
    "subscribe to my channel",
    "like and subscribe",
    "subtitles by the amara.org community",
    "subtitles by",
    "captions by",
    "transcription by",
    "...",
    ". . .",
    "bye.",
    "bye",
    "goodbye.",
    "goodbye",
    "okay.",
    "okay",
    "ok.",
    "ok",
    "you",
    "you.",
    ".",
    "!",
    "?",
}

class SpeechRecognizer:
    """Transcribes audio to text and extracts spoken digits."""

    def __init__(self):
        self.model = None

    def _get_model(self) -> WhisperModel:
        """Lazy-load Whisper model — auto-selects CPU or GPU."""
        if self.model is None:
            self.model = WhisperModel(
                WHISPER_MODEL_SIZE,
                device=DEVICE,
                compute_type=COMPUTE_TYPE,
            )
        return self.model

    def transcribe(self, audio_path: str) -> dict:
        """
        Transcribe audio file and extract digits.
        Detects and filters Whisper hallucinations on silent audio.

        Returns:
            dict with: transcription, normalized, digits_only, language, is_hallucination.
        """
        model = self._get_model()

        # Whisper transcription with beam search and built-in VAD filter
        segments, info = model.transcribe(
            audio_path,
            beam_size=5,
            vad_filter=True,
        )

        # Combine all segments into a single transcription
        transcription = " ".join(segment.text for segment in segments).strip()
        normalized = self._normalize_text(transcription)

        # Check if transcription is a known hallucination
        is_hallucination = self._is_hallucination(normalized)

        # If hallucination detected, treat as empty transcription
        if is_hallucination:
            digits = ""
        else:
            digits = self._extract_digits(normalized)

        return {
            "transcription": transcription,
            "normalized": normalized,
            "digits_only": digits,
            "language": info.language if info else None,
            "is_hallucination": is_hallucination,
        }

    def _normalize_text(self, text: str) -> str:
        """Lowercase and collapse whitespace."""
        return re.sub(r"\s+", " ", text.strip().lower())

    def _is_hallucination(self, normalized_text: str) -> bool:
        """
        Check if the transcription is a known Whisper hallucination.
        These occur on silent or non-speech audio.
        """
        if not normalized_text:
            return False

        # Exact match against known hallucination phrases
        if normalized_text in WHISPER_HALLUCINATIONS:
            return True

        # Check if text starts with common hallucination prefixes
        hallucination_prefixes = [
            "thanks for watching",
            "thank you for watching",
            "please subscribe",
            "subtitles by",
            "captions by",
        ]
        for prefix in hallucination_prefixes:
            if normalized_text.startswith(prefix):
                return True

        return False

    def _extract_digits(self, text: str) -> str:
        """
        Extract digits from text — handles both formats:
        - Numeric: "7 3 8 2 9" → "73829"
        - Words: "seven three eight two nine" → "73829"
        - Mixed: "seven 3 eight" → "738"
        """
        result = []

        for word in text.split():
            # Remove punctuation from word
            clean = re.sub(r"[^\w]", "", word)

            if not clean:
                continue

            # Check if it's a digit character
            if clean.isdigit():
                result.append(clean)
            # Check if it's a word representing a digit
            elif clean in WORD_TO_DIGIT:
                result.append(WORD_TO_DIGIT[clean])

        return "".join(result)