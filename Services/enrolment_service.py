import asyncio
# ===========================================================
# SpeakSecure — Enrolment Service
# Manages voice profile creation and expansion.
#
# Two separate operations:
#   enrol_user()  - creates a NEW voice profile (fails if user exists)
#   add_sample()  - adds a sample to an EXISTING profile (fails if not)
#
# Both share the same audio validation, anti-spoofing and embedding
# extraction pipeline via the private _process_audio() helper.
#
# AudioProcessor and AudioValidator are injected so the entire app
# shares one instance of each (saves memory; avoids two VAD models).
# ===========================================================

from fastapi import UploadFile
from loguru import logger

from constants import (
    SIMILARITY_THRESHOLD,
    MAX_SAMPLES_PER_USER,
    SPOOF_CONFIDENCE_THRESHOLD_ENROL,
)
from Services.audio_service import AudioService
from Services.embedding_service import EmbeddingService
from Services.spoofing_service import SpoofingService
from Services.speech_service import SpeechService
from Storage.voiceprint_repository import VoiceprintRepository
from Core.audio_processor import AudioProcessor
from Core.audio_validator import AudioValidator


class EnrolmentService:
    """Manages the complete user voice enrolment process."""

    def __init__(
        self,
        audio_service: AudioService,
        embedding_service: EmbeddingService,
        spoofing_service: SpoofingService,
        speech_service: SpeechService,
        voiceprint_repository: VoiceprintRepository,
        audio_processor: AudioProcessor = None,
        audio_validator: AudioValidator = None,
    ):
        self.audio_service = audio_service
        self.embedding_service = embedding_service
        self.spoofing_service = spoofing_service
        self.speech_service = speech_service
        self.voiceprint_repository = voiceprint_repository

        # Use injected singletons; fall back to fresh instances for tests
        # that construct the service directly without DI.
        self.audio_processor = audio_processor if audio_processor is not None else AudioProcessor()
        self.audio_validator = audio_validator if audio_validator is not None else AudioValidator()

    # ==================== Public API ====================

    async def enrol_user(self, user_id: str, audio_file: UploadFile) -> dict:
        """
        Register a NEW user with their first voice sample.
        Fails if the username is already taken.
        """
        logger.info(f"New user registration: '{user_id}'")

        # Username must not already exist
        if self.voiceprint_repository.user_exists(user_id):
            logger.warning(f"Registration rejected: username '{user_id}' already taken")
            raise ValueError(
                f"Username '{user_id}' is already taken. "
                f"Please choose a different username or sign in instead."
            )

        saved_path = None
        try:
            # Run the shared audio pipeline (save, validate, anti-spoof, embed)
            saved_path, embedding = await self._process_audio(user_id, audio_file)

            # Store the first embedding - creates the profile on disk
            save_result = self.voiceprint_repository.add_embedding(
                user_id, embedding
            )

            logger.info(
                f"Registration successful for user '{user_id}' - "
                f"{save_result['num_samples']} sample(s) stored"
            )

            return {
                "user_id": user_id,
                "num_samples": save_result["num_samples"],
                "max_samples": MAX_SAMPLES_PER_USER,
                "message": (
                    f"Voice profile created for user '{user_id}'. "
                    f"You can now sign in with your voice."
                ),
            }

        finally:
            # Always cleanup temp file, even if an error occurred
            if saved_path:
                self.audio_service.delete_file(saved_path)

    async def add_sample(self, user_id: str, audio_file: UploadFile) -> dict:
        """
        Add an additional voice sample to an EXISTING user's profile.
        Fails if user does not exist, the max sample limit is reached,
        or the voice doesn't match the enrolled profile.
        """
        logger.info(f"Adding sample for user '{user_id}'")

        # User must exist
        if not self.voiceprint_repository.user_exists(user_id):
            raise FileNotFoundError(
                f"No voice profile found for user '{user_id}'. "
                f"Please register first."
            )

        # Must be under the sample limit
        current_count = self.voiceprint_repository.get_sample_count(user_id)
        if current_count >= MAX_SAMPLES_PER_USER:
            logger.warning(
                f"Add sample rejected for '{user_id}': limit reached "
                f"({current_count}/{MAX_SAMPLES_PER_USER})"
            )
            raise ValueError(
                f"Maximum number of voice samples reached ({MAX_SAMPLES_PER_USER}). "
                f"You already have {current_count} samples stored."
            )

        saved_path = None
        try:
            # Run the shared audio pipeline (save, validate, anti-spoof, embed)
            saved_path, embedding = await self._process_audio(user_id, audio_file)

            # Voice identity check - new sample must match existing profile
            enrolled_profile = self.voiceprint_repository.load_profile(user_id)
            similarity = self.embedding_service.cosine_similarity(
                enrolled_profile, embedding
            )
            logger.debug(f"Voice match check: similarity = {similarity:.4f}")

            if similarity < SIMILARITY_THRESHOLD:
                logger.warning(
                    f"Add sample rejected for '{user_id}': voice doesn't match "
                    f"(similarity: {similarity:.4f}, threshold: {SIMILARITY_THRESHOLD})"
                )
                raise ValueError(
                    f"This voice doesn't match your enrolled profile. "
                    f"Samples must come from the same person "
                    f"(match: {similarity * 100:.1f}%, "
                    f"minimum required: {SIMILARITY_THRESHOLD * 100:.0f}%)."
                )

            # Store the additional embedding
            save_result = self.voiceprint_repository.add_embedding(
                user_id, embedding
            )

            logger.info(
                f"Sample added for user '{user_id}' - "
                f"now has {save_result['num_samples']} sample(s)"
            )

            return {
                "user_id": user_id,
                "num_samples": save_result["num_samples"],
                "max_samples": MAX_SAMPLES_PER_USER,
                "message": (
                    f"Voice sample added. You now have {save_result['num_samples']} "
                    f"of {MAX_SAMPLES_PER_USER} samples stored."
                ),
            }

        finally:
            if saved_path:
                self.audio_service.delete_file(saved_path)

    # ==================== Private helpers ====================

    async def _process_audio(self, user_id: str, audio_file: UploadFile):
        """
        Shared audio processing pipeline used by both enrol and add_sample.
        Saves the audio, runs validation, anti-spoofing, and extracts the
        voice embedding.

        Returns:
            Tuple of (saved_path, embedding).
        """
        # Step 1: Save uploaded audio to temp directory
        saved_path = await self.audio_service.save_temp_audio(audio_file)
        logger.debug(f"Audio saved to {saved_path}")

        # Step 2: Validate that audio contains real human speech
        # ML call — offload to thread pool to avoid blocking event loop.
        waveform = await asyncio.to_thread(self.audio_processor.process, saved_path)
        await asyncio.to_thread(self.audio_validator.validate, waveform, "enrolment")

        # Step 3: Transcription check - Whisper must recognize actual speech
        # Whisper is the slowest call (~5-15s) — without to_thread this blocks
        # FastAPI's event loop and stalls other concurrent requests.
        transcription = await asyncio.to_thread(self.speech_service.transcribe_audio, saved_path)

        # Reject Whisper hallucinations (common on silent/noise audio)
        if transcription.get("is_hallucination"):
            logger.warning(
                f"Rejected: Whisper hallucination detected "
                f"('{transcription['normalized']}')"
            )
            raise ValueError(
                "Audio rejected: no recognizable speech detected. "
                "Please speak clearly into the microphone."
            )

        if not transcription["normalized"].strip():
            raise ValueError(
                "Audio rejected: no recognizable human speech found. "
                "Please ensure you are speaking clearly."
            )
        logger.debug(f"Transcription: '{transcription['normalized']}'")

        # Step 4: AASIST anti-spoofing check (STRICT threshold)
        # Enrolment uses a low threshold to reject any suspicious audio.
        # We don't want TTS or replays to poison the stored voice profile.
        spoof_result = await asyncio.to_thread(
            self.spoofing_service.analyze_audio,
            saved_path,
            threshold=SPOOF_CONFIDENCE_THRESHOLD_ENROL,
        )
        logger.debug(
            f"Spoof check (enrol, strict): {spoof_result['label']} "
            f"(confidence: {spoof_result['confidence']}, "
            f"threshold: {spoof_result['threshold_used']})"
        )

        if spoof_result["spoof_detected"]:
            logger.warning(f"Rejected: spoofing detected for user '{user_id}'")
            raise ValueError(
                f"Audio rejected: appears to be spoofed "
                f"(confidence: {spoof_result['confidence']:.2f})."
            )

        # Step 5: Extract 192-dim voice embedding via ECAPA-TDNN
        embedding = await asyncio.to_thread(self.embedding_service.extract_embedding, saved_path)

        return saved_path, embedding