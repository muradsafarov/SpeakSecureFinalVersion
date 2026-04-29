import asyncio
# ===========================================================
# SpeakSecure — Verification Service
# Orchestrates the complete voice verification pipeline.
# 12-step process: rate limit → validate → anti-spoof →
# speech recognition → challenge match → voice compare → decision.
#
# Rate limiting logic:
#   - Check lockout status BEFORE processing
#   - On successful verification → reset failed counter
#   - On failed verification (any reason) → increment failed counter
#   - After MAX_FAILED_ATTEMPTS failures, user is locked out
#
# AudioProcessor and AudioValidator are injected so the entire app
# shares one instance of each (saves memory; avoids two VAD models).
# ===========================================================

from fastapi import UploadFile
from loguru import logger

from constants import (
    SIMILARITY_THRESHOLD,
    BORDERLINE_THRESHOLD,
    SPOOF_CONFIDENCE_THRESHOLD_VERIFY,
)
from Services.audio_service import AudioService
from Services.embedding_service import EmbeddingService
from Services.speech_service import SpeechService
from Services.spoofing_service import SpoofingService
from Services.challenge_service import ChallengeService
from Storage.voiceprint_repository import VoiceprintRepository
from Security.rate_limiter import RateLimiter
from Core.audio_processor import AudioProcessor
from Core.audio_validator import AudioValidator

class VerificationService:
    """Manages the complete voice verification process."""

    def __init__(
        self,
        audio_service: AudioService,
        embedding_service: EmbeddingService,
        speech_service: SpeechService,
        spoofing_service: SpoofingService,
        challenge_service: ChallengeService,
        voiceprint_repository: VoiceprintRepository,
        rate_limiter: RateLimiter,
        audio_processor: AudioProcessor = None,
        audio_validator: AudioValidator = None,
    ):
        self.audio_service = audio_service
        self.embedding_service = embedding_service
        self.speech_service = speech_service
        self.spoofing_service = spoofing_service
        self.challenge_service = challenge_service
        self.voiceprint_repository = voiceprint_repository
        self.rate_limiter = rate_limiter

        # Use injected singletons; fall back to fresh instances for tests
        # that construct the service directly without DI.
        self.audio_processor = audio_processor if audio_processor is not None else AudioProcessor()
        self.audio_validator = audio_validator if audio_validator is not None else AudioValidator()

    async def verify_user(self, user_id: str, audio_file: UploadFile) -> dict:
        """
        Full verification pipeline.
        Each step can reject the request early (fail-fast approach).
        """
        saved_path = None
        logger.info(f"Verification started for user '{user_id}'")

        try:
            # Step 1: Check if user is locked out from previous failed attempts
            if not await self.rate_limiter.is_allowed(user_id):
                retry_after = await self.rate_limiter.get_lockout_seconds_remaining(user_id)
                logger.warning(f"User '{user_id}' is locked out for {retry_after} more seconds")
                raise ValueError(
                    f"Too many failed attempts for user '{user_id}'. "
                    f"Account is temporarily locked. Try again in {retry_after} seconds."
                )

            # Step 2: Ensure user has an enrolled voice profile
            if not self.voiceprint_repository.user_exists(user_id):
                raise FileNotFoundError(
                    f"No enrolled voice profile found for user '{user_id}'."
                )

            # Step 3: Ensure an active challenge exists
            if not await self.challenge_service.has_active_challenge(user_id):
                raise ValueError(
                    f"No active challenge for user '{user_id}'. "
                    f"Request a new challenge first."
                )

            # Step 4: Save uploaded audio
            saved_path = await self.audio_service.save_temp_audio(audio_file)

            # Step 5: Validate audio contains real human speech.
            # ML call — offload to thread pool so we don't block the event loop.
            #
            # Both `process` and `validate` can raise ValueError on garbage
            # input (silence, too-short clips, mostly-noise). We catch and
            # COUNT THESE AS FAILED ATTEMPTS so an attacker can't bypass the
            # per-user lockout by spamming malformed audio — without this,
            # validate() would raise and the request would exit through the
            # outer try/finally without ever incrementing the failure counter.
            try:
                waveform = await asyncio.to_thread(self.audio_processor.process, saved_path)
                await asyncio.to_thread(self.audio_validator.validate, waveform, "verification")
            except ValueError:
                await self.rate_limiter.record_failed_attempt(user_id)
                raise

            # Step 6: AASIST anti-spoofing check (LENIENT threshold).
            # Verification uses a high threshold to avoid false rejections
            # on genuine microphone input — AASIST tends to be oversensitive
            # to real user audio. Only clear-cut spoofs get blocked here.
            spoof_result = await asyncio.to_thread(
                self.spoofing_service.analyze_audio,
                saved_path,
                threshold=SPOOF_CONFIDENCE_THRESHOLD_VERIFY,
            )
            logger.debug(
                f"Spoof check (verify, lenient): {spoof_result['label']} "
                f"(confidence: {spoof_result['confidence']}, "
                f"threshold: {spoof_result['threshold_used']})"
            )

            if spoof_result["spoof_detected"]:
                # Consume the challenge so it can't be reused
                await self.challenge_service.verify_challenge(user_id, "")
                logger.warning(f"Spoofing detected for user '{user_id}'")
                await self.rate_limiter.record_failed_attempt(user_id)
                return await self._build_result(
                    user_id=user_id,
                    decision="rejected",
                    verified=False,
                    message=f"Spoofing detected for user '{user_id}'.",
                    similarity_score=0.0,
                    challenge_passed=False,
                    recognized_digits="",
                    spoof_result=spoof_result,
                )

            # Step 7: Whisper speech-to-text
            # Whisper is the slowest call (~5-15s) — without to_thread this blocks
            # FastAPI's event loop and causes other concurrent requests to stall.
            speech_result = await asyncio.to_thread(self.speech_service.transcribe_audio, saved_path)
            recognized_digits = speech_result["digits_only"]
            logger.debug(f"Recognized digits: '{recognized_digits}'")

            # Step 8: Challenge verification (atomic — lock protects from race conditions)
            challenge_passed = await self.challenge_service.verify_challenge(
                user_id, recognized_digits
            )

            if not challenge_passed:
                logger.info(f"Challenge failed for user '{user_id}' — recognized: '{recognized_digits}'")
                await self.rate_limiter.record_failed_attempt(user_id)
                return await self._build_result(
                    user_id=user_id,
                    decision="rejected",
                    verified=False,
                    message=f"Challenge verification failed for user '{user_id}'.",
                    similarity_score=0.0,
                    challenge_passed=False,
                    recognized_digits=recognized_digits,
                    spoof_result=spoof_result,
                )

            # Step 9: Extract voice embedding
            current_embedding = await asyncio.to_thread(self.embedding_service.extract_embedding, saved_path)

            # Step 10: Compare with enrolled profile
            enrolled_profile = self.voiceprint_repository.load_profile(user_id)
            similarity_score = self.embedding_service.cosine_similarity(
                enrolled_profile, current_embedding
            )
            logger.debug(f"Similarity score: {similarity_score:.4f}")

            # Step 11: Final decision + track failed/successful attempts
            if similarity_score >= SIMILARITY_THRESHOLD:
                # SUCCESS: reset failed counter
                await self.rate_limiter.reset_attempts(user_id)
                decision = "accepted"
                verified = True
                retry = False
                message = f"User '{user_id}' verified successfully."
            elif similarity_score >= BORDERLINE_THRESHOLD:
                # BORDERLINE: count as failed (user should try again with better recording)
                await self.rate_limiter.record_failed_attempt(user_id)
                decision = "retry"
                verified = False
                retry = True
                message = f"Voice match is borderline for user '{user_id}'. Please try again."
            else:
                # REJECTED: count as failed
                await self.rate_limiter.record_failed_attempt(user_id)
                decision = "rejected"
                verified = False
                retry = False
                message = f"Voice verification failed for user '{user_id}'."

            logger.info(f"Verification result for '{user_id}': {decision} (score: {similarity_score:.4f})")

            return await self._build_result(
                user_id=user_id,
                decision=decision,
                verified=verified,
                message=message,
                similarity_score=similarity_score,
                challenge_passed=True,
                recognized_digits=recognized_digits,
                spoof_result=spoof_result,
                retry_required=retry,
            )

        finally:
            # Step 12: Always cleanup temp file
            if saved_path:
                self.audio_service.delete_file(saved_path)

    async def _build_result(
        self,
        user_id: str,
        decision: str,
        verified: bool,
        message: str,
        similarity_score: float,
        challenge_passed: bool,
        recognized_digits: str,
        spoof_result: dict,
        retry_required: bool = False,
    ) -> dict:
        """
        Build a standardized verification result dictionary.
        Threshold values (SIMILARITY_THRESHOLD, BORDERLINE_THRESHOLD) are
        deliberately NOT included — they are constants exposed via /status
        rather than per-request configuration.
        """
        remaining = await self.rate_limiter.get_remaining_attempts(user_id)

        return {
            "user_id": user_id,
            "verified": verified,
            "retry_required": retry_required,
            "decision": decision,
            "message": message,
            "similarity_score": round(similarity_score, 4),
            "challenge_passed": challenge_passed,
            "recognized_digits": recognized_digits,
            "spoof_detected": spoof_result["spoof_detected"],
            "spoof_label": spoof_result["label"],
            "spoof_confidence": spoof_result["confidence"],
            "remaining_attempts": remaining,
        }