# ===========================================================
# SpeakSecure — Constants
# All fixed values used across the project.
# Change these to tune system behavior without modifying code.
# ===========================================================

# --- Audio Processing ---
TARGET_SAMPLE_RATE = 16000              # All models expect 16kHz audio
MIN_AUDIO_DURATION_SECONDS = 1.0       # Reject audio shorter than 1 second
MAX_AUDIO_DURATION_SECONDS = 15.0      # Reject audio longer than 15 seconds

ALLOWED_AUDIO_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".aac",
    ".m4a",
    ".flac",
    ".ogg",
}

# --- Voice Verification ---
SIMILARITY_THRESHOLD = 0.35            # Minimum cosine similarity for acceptance
BORDERLINE_THRESHOLD = 0.32            # Below this = rejected, above = retry zone

# --- Enrolment ---
MAX_SAMPLES_PER_USER = 3               # Maximum voice samples a user can store

# --- Challenge ---
CHALLENGE_LENGTH = 5                   # Number of random digits in each challenge
CHALLENGE_EXPIRATION_SECONDS = 60      # Challenge expires after 60 seconds

# --- Rate Limiting ---
MAX_FAILED_ATTEMPTS = 5                # Block user after this many failed verifications
LOCKOUT_DURATION_SECONDS = 60          # How long the user stays locked out (set to 3600 for 1 hour)

# --- Anti-Spoofing ---
# Two separate thresholds for a security/UX trade-off:
#   - Enrolment should be STRICT to prevent poisoning the voice profile
#     with suspicious audio (TTS, replays, mixed sources). A low threshold
#     rejects more aggressively.
#   - Verification should be LENIENT since legitimate users often get
#     flagged by AASIST on genuine microphone input. A high threshold
#     only rejects very confident spoofs during sign-in.
SPOOF_CONFIDENCE_THRESHOLD_ENROL = 0.75    # Strict: reject anything suspicious at enrolment
SPOOF_CONFIDENCE_THRESHOLD_VERIFY = 1.25   # Lenient: only reject very confident spoofs during sign-in

# --- OAuth 2.0 / Third-Party Integration ---
# Authorization codes issued by GET /authorize after a successful voice
# verification. Third-party backends must exchange them via POST /token.
# 10 seconds is the OAuth 2.0 best-practice value: long enough for the
# full redirect → backend exchange round trip, short enough that a
# leaked code cannot be replayed minutes later.
AUTHORIZATION_CODE_TTL_SECONDS = 10

# --- Audio Validation (VAD-based speech ratio thresholds) ---
# After Silero VAD runs, what fraction of the audio must contain
# detected speech?
#   - Enrolment is STRICTER (40%) — we want clean voice profiles,
#     not noisy or mostly-silent recordings.
#   - Verification is LENIENT (30%) — sign-in is shorter and
#     real-world conditions vary (background, microphone quality).
ENROL_MIN_SPEECH_RATIO = 0.40
VERIFY_MIN_SPEECH_RATIO = 0.30

# Minimum RMS energy for a recording to be considered audible at all.
# Below this we treat the audio as effectively silent and reject before
# even running VAD — saves an inference call on garbage input.
MIN_SPEECH_ENERGY = 0.005

# --- Audio Conversion (ffmpeg) ---
# Hard cap on how long ffmpeg can spend converting an upload to WAV.
# Real conversions take 1-3s; 30s is a generous ceiling that catches
# malicious/malformed inputs designed to hang the conversion (e.g.
# decompression bombs) without affecting normal users.
FFMPEG_TIMEOUT_SECONDS = 30

# --- API Info ---
API_TITLE = "SpeakSecure API"
API_DESCRIPTION = "Privacy-first open-source voice authentication API"
API_VERSION = "1.0.0"