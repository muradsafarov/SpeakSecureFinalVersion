# ===========================================================
# SpeakSecure — Dependency Container
# Creates and wires all service instances in one place.
# Acts as a simple dependency injection container.
# Import from here in API routes — never instantiate directly.
#
# Singletons here are shared across the whole application:
#   - Core processors (audio I/O, VAD, validators) — small but
#     used everywhere; one instance prevents memory duplication
#     (especially the VAD model which is loaded once)
#   - Services (audio, embedding, speech, spoofing, challenge)
#   - Storage and security
#   - Orchestrators (enrolment, verification) — wired with the above
# ===========================================================

# --- Core processors (shared across services) ---
from Core.audio_processor import AudioProcessor
from Core.audio_validator import AudioValidator
from Core.vad import VoiceActivityDetector

# Single shared VAD instance (the Silero model is ~2MB but we only
# want ONE copy loaded into memory across the whole app).
vad = VoiceActivityDetector()

# Single shared audio processor (load, resample, normalize)
audio_processor = AudioProcessor()

# Single shared audio validator — uses the shared VAD above
audio_validator = AudioValidator(vad=vad)

# --- Service-layer singletons ---
from Services.audio_service import AudioService
from Services.embedding_service import EmbeddingService
from Services.challenge_service import ChallengeService
from Services.speech_service import SpeechService
from Services.spoofing_service import SpoofingService
from Services.enrolment_service import EnrolmentService
from Services.verification_service import VerificationService
from Services.oauth_service import OAuthService
from Storage.voiceprint_repository import VoiceprintRepository
from Storage.api_key_repository import ApiKeyRepository
from Storage.authorization_code_repository import AuthorizationCodeRepository
from Storage.usage_repository import UsageRepository
from Security.rate_limiter import RateLimiter, ApiKeyRateLimiter

audio_service = AudioService()
embedding_service = EmbeddingService(
    audio_processor=audio_processor,
    vad=vad,
)
challenge_service = ChallengeService()
speech_service = SpeechService()
spoofing_service = SpoofingService()
voiceprint_repository = VoiceprintRepository()

# Per-user rate limiter (verification brute-force protection)
rate_limiter = RateLimiter()

# API key infrastructure (integration auth + per-key rate limit)
api_key_repository = ApiKeyRepository()
usage_repository = UsageRepository()
api_key_rate_limiter = ApiKeyRateLimiter(usage_repository=usage_repository)

# OAuth 2.0 authorization code flow.
# Used by GET /authorize and POST /token to issue and exchange
# short-lived authorization codes for third-party integrations.
authorization_code_repository = AuthorizationCodeRepository()
oauth_service = OAuthService(code_repository=authorization_code_repository)

# --- Orchestrator services (wired with their dependencies) ---

# Enrolment: audio → validate → transcription check → anti-spoof → embed → store
enrolment_service = EnrolmentService(
    audio_service=audio_service,
    embedding_service=embedding_service,
    spoofing_service=spoofing_service,
    speech_service=speech_service,
    voiceprint_repository=voiceprint_repository,
    audio_processor=audio_processor,
    audio_validator=audio_validator,
)

# Verification: rate limit → validate → anti-spoof → STT → challenge → compare → decide
verification_service = VerificationService(
    audio_service=audio_service,
    embedding_service=embedding_service,
    speech_service=speech_service,
    spoofing_service=spoofing_service,
    challenge_service=challenge_service,
    voiceprint_repository=voiceprint_repository,
    rate_limiter=rate_limiter,
    audio_processor=audio_processor,
    audio_validator=audio_validator,
)