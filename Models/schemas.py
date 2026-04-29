# ===========================================================
# SpeakSecure — Pydantic Schemas
# All request/response models for the API.
# Defines the structure of JSON responses returned by each endpoint.
# ===========================================================

from typing import Optional

from pydantic import BaseModel


# --- API Key Info ---
# Internal model used by the require_api_key dependency to pass the
# authenticated key's context into route handlers. NOT part of any
# HTTP response — it stays server-side.

class ApiKeyInfo(BaseModel):
    id: int                     # Database ID of the key
    name: str                   # Human-readable name (e.g. "SpeakSecure Self-Service")
    key_prefix: str             # First 12 chars of the key (for logs)
    origins: list[str]          # Allowed origins — empty means any
    rate_limit_per_hour: int    # Max requests per hour for this key


# --- Enrolment Response ---
# Returned by POST /enrol (new registration) and POST /enrol/add-sample

class EnrolmentResponse(BaseModel):
    success: bool               # Whether enrolment completed successfully
    user_id: str                # The enrolled user's identifier
    num_samples: int            # Total number of voice samples stored for this user
    max_samples: int            # Maximum samples allowed per user
    message: str                # Human-readable status message


# --- Enrolment Check Response ---
# Returned by GET /enrol/check/{user_id} to check if username is taken

class EnrolmentCheckResponse(BaseModel):
    exists: bool                # Whether a voice profile exists for this user
    user_id: str                # The requested user ID
    num_samples: int            # Samples stored (0 if user doesn't exist)
    max_samples: int            # Maximum samples allowed per user
    can_add_sample: bool        # True if user exists and has < max samples


# --- Challenge Response ---
# Returned by POST /challenge with the digits the user must speak

class ChallengeResponse(BaseModel):
    success: bool               # Whether challenge was generated successfully
    user_id: str                # The user this challenge belongs to
    challenge: str              # Random digit string (e.g. "73829")
    expires_in_seconds: int     # Seconds until this challenge expires
    message: str                # Human-readable instructions


# --- Verification Response ---
# Returned by POST /verify with the full verification result.
# NOTE: similarity thresholds are NOT included here — they are configuration
# constants exposed at GET /status. Keeping the verify response free of
# constant values keeps it concise and easier to consume.

class VerificationResponse(BaseModel):
    success: bool               # Whether the request was processed (not verification result)
    verified: bool              # True if the user's identity was confirmed
    retry_required: bool        # True if similarity was borderline — user should try again
    decision: str               # "accepted", "rejected", or "retry"
    message: str                # Human-readable explanation
    user_id: str                # The user who was verified
    similarity_score: float     # Cosine similarity between enrolled and test voice (0.0–1.0)
    challenge_passed: bool      # Whether spoken digits matched the challenge
    recognized_digits: str      # Digits extracted from speech by Whisper
    spoof_detected: bool        # Whether AASIST flagged the audio as synthetic
    spoof_label: str            # "bonafide" or "spoof"
    spoof_confidence: float     # AASIST's confidence in its spoofing prediction
    remaining_attempts: int     # How many of verification attempts the user has left


# ==================== OAuth 2.0 Flow Schemas ====================

# --- Authorize Challenge Response ---
# Returned by POST /authorize/challenge — the internal challenge endpoint
# used by the /authorize HTML page. No X-API-Key required because the
# request is authenticated by the (client_id, redirect_uri, state) trio
# the page received from GET /authorize.

class AuthorizeChallengeResponse(BaseModel):
    success: bool               # Whether challenge was generated
    challenge: str              # Random digit string the user must speak
    expires_in_seconds: int     # Seconds until this challenge expires


# --- Authorize Sign-In Response ---
# Returned by POST /authorize/submit-signin.
# On success: a redirect_url that the page navigates to,
# carrying ?code=... and ?state=... back to the integrator's site.

class AuthorizeSubmitResponse(BaseModel):
    success: bool               # Whether the request was processed
    verified: bool              # True if voice verification succeeded
    retry_required: bool        # True if borderline — try again
    decision: str               # "accepted", "rejected", or "retry"
    message: str                # Human-readable explanation
    user_id: str                # The user who was verified
    similarity_score: float
    challenge_passed: bool
    recognized_digits: str
    spoof_detected: bool
    spoof_label: str
    spoof_confidence: float
    remaining_attempts: int
    # On a successful verification, this holds the URL the page should
    # navigate to (integrator's redirect_uri + code + state). Otherwise
    # null — the page stays on /authorize and lets the user retry.
    redirect_url: Optional[str] = None
class TokenRequest(BaseModel):
    code: str                   # The authorization code received via redirect
    redirect_uri: str           # Same redirect_uri used during /authorize


# --- Token Exchange Response ---
# Response to POST /token. On success: full verification details.
# On failure: a generic reason that doesn't leak whether the code was
# unknown vs expired vs already used vs from a different API key.

class TokenResponse(BaseModel):
    valid: bool                          # Whether the code was accepted
    reason: Optional[str] = None         # If invalid, why (generic for security)
    user_id: Optional[str] = None        # Who was verified (if valid)
    verified: Optional[bool] = None      # The verification outcome
    decision: Optional[str] = None       # "accepted" / "rejected" / "retry"
    similarity_score: Optional[float] = None


# --- OAuth Client Info Response ---
# Public endpoint response — returns the human-readable name registered
# against a given client_id (API key). Used by the Demo standalone to
# show 'Sign in to <name>' banners during the redirect-register flow.
# Returns ONLY the public name, never any secret material — and only
# for keys that have at least one redirect_uri registered (i.e. real
# OAuth integrators, not self-service keys).

class ClientInfoResponse(BaseModel):
    name: str                            # Human name e.g. 'Acme Shop'