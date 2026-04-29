# ===========================================================
# SpeakSecure — Verification Tests
# Integration tests for the /verify endpoint via FastAPI TestClient.
# Pipeline tests mock AudioValidator, SpoofingService, and SpeechService
# since synthetic audio won't pass real speech/spoof detection.
# ===========================================================

import io
import asyncio
import pytest
import torch
import torchaudio
from unittest.mock import patch
from fastapi.testclient import TestClient

from main import app
from Services.dependencies import (
    voiceprint_repository,
    challenge_service,
    rate_limiter,
)

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture(autouse=True)
def cleanup_after_test():
    """Clean up test data after each test to prevent state leaking."""
    yield
    voiceprint_repository.delete_user("test_user")
    # Reset rate limiter state for the test user (new lockout-based API)
    rate_limiter.failed_counts.pop("test_user", None)
    rate_limiter.locked_until.pop("test_user", None)

def _generate_test_audio(duration_seconds: float = 3.0) -> io.BytesIO:
    """Generate a synthetic WAV audio file in memory for testing."""
    sample_rate = 16000
    samples = int(duration_seconds * sample_rate)
    waveform = torch.randn(1, samples)

    buffer = io.BytesIO()
    torchaudio.save(buffer, waveform, sample_rate, format="wav")
    buffer.seek(0)
    return buffer

# Mock returns for components that require real speech.
# The mock shape mirrors what the real services return, minus redundant fields.
MOCK_VALIDATOR = {"is_valid": True, "checks": {}, "message": "ok"}
MOCK_SPOOF = {
    "spoof_detected": False,
    "confidence": 0.1,
    "label": "bonafide",
    "threshold_used": 1.0,
}
MOCK_ENROL_TRANSCRIPTION = {
    "transcription": "hello",
    "normalized": "hello",
    "digits_only": "",
    "language": "en",
    "is_hallucination": False,
}

def _enrol_test_user(client):
    """Helper: enrol a test user with mocked validation."""
    with patch("Services.enrolment_service.AudioValidator.validate", return_value=MOCK_VALIDATOR), \
         patch("Services.enrolment_service.SpoofingService.analyze_audio", return_value=MOCK_SPOOF), \
         patch("Services.enrolment_service.SpeechService.transcribe_audio", return_value=MOCK_ENROL_TRANSCRIPTION):
        audio = _generate_test_audio()
        client.post(
            "/api/v1/enrol",
            data={"user_id": "test_user"},
            files={"audio_file": ("test.wav", audio, "audio/wav")},
        )


def _generate_challenge_sync(user_id: str):
    """Helper: run async generate_challenge from sync test code."""
    return asyncio.run(challenge_service.generate_challenge(user_id))


def _mock_verify_transcription(challenge_digits: str):
    """Create a mock transcription that returns specific digits."""
    return {
        "transcription": challenge_digits,
        "normalized": challenge_digits,
        "digits_only": challenge_digits,
        "language": "en",
        "is_hallucination": False,
    }

class TestVerifyPreChecks:
    """Tests for pre-verification checks (before audio processing)."""

    def test_user_not_found(self, client):
        audio = _generate_test_audio()
        response = client.post(
            "/api/v1/verify",
            data={"user_id": "nonexistent_user"},
            files={"audio_file": ("test.wav", audio, "audio/wav")},
        )
        assert response.status_code == 404

    def test_no_active_challenge(self, client):
        _enrol_test_user(client)
        audio = _generate_test_audio()
        response = client.post(
            "/api/v1/verify",
            data={"user_id": "test_user"},
            files={"audio_file": ("test.wav", audio, "audio/wav")},
        )
        assert response.status_code == 400
        assert "challenge" in response.json()["detail"].lower()

    def test_missing_audio(self, client):
        response = client.post(
            "/api/v1/verify",
            data={"user_id": "test_user"},
        )
        assert response.status_code == 422

    def test_missing_user_id(self, client):
        audio = _generate_test_audio()
        response = client.post(
            "/api/v1/verify",
            files={"audio_file": ("test.wav", audio, "audio/wav")},
        )
        assert response.status_code == 422

class TestVerifyPipeline:
    """Tests for the full verification pipeline response."""

    def test_verify_returns_response(self, client):
        _enrol_test_user(client)
        challenge = _generate_challenge_sync("test_user")

        mock_transcription = _mock_verify_transcription(challenge["challenge"])

        with patch("Services.verification_service.AudioValidator.validate", return_value=MOCK_VALIDATOR), \
             patch("Services.verification_service.SpoofingService.analyze_audio", return_value=MOCK_SPOOF), \
             patch("Services.verification_service.SpeechService.transcribe_audio", return_value=mock_transcription):
            audio = _generate_test_audio()
            response = client.post(
                "/api/v1/verify",
                data={"user_id": "test_user"},
                files={"audio_file": ("test.wav", audio, "audio/wav")},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["user_id"] == "test_user"
        assert "similarity_score" in data
        assert "decision" in data
        assert "remaining_attempts" in data

    def test_verify_response_has_all_fields(self, client):
        _enrol_test_user(client)
        challenge = _generate_challenge_sync("test_user")

        mock_transcription = _mock_verify_transcription(challenge["challenge"])

        with patch("Services.verification_service.AudioValidator.validate", return_value=MOCK_VALIDATOR), \
             patch("Services.verification_service.SpoofingService.analyze_audio", return_value=MOCK_SPOOF), \
             patch("Services.verification_service.SpeechService.transcribe_audio", return_value=mock_transcription):
            audio = _generate_test_audio()
            response = client.post(
                "/api/v1/verify",
                data={"user_id": "test_user"},
                files={"audio_file": ("test.wav", audio, "audio/wav")},
            )

        data = response.json()
        # Threshold constants are exposed via /status, not in verify responses
        required_fields = [
            "success", "verified", "retry_required", "decision",
            "message", "user_id", "similarity_score",
            "challenge_passed", "recognized_digits",
            "spoof_detected", "spoof_label", "spoof_confidence",
            "remaining_attempts",
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

class TestVerifyChallenge:
    """Tests for challenge one-time use within the verification pipeline."""

    def test_challenge_consumed_after_verify(self, client):
        _enrol_test_user(client)
        challenge = _generate_challenge_sync("test_user")

        mock_transcription = _mock_verify_transcription(challenge["challenge"])

        with patch("Services.verification_service.AudioValidator.validate", return_value=MOCK_VALIDATOR), \
             patch("Services.verification_service.SpoofingService.analyze_audio", return_value=MOCK_SPOOF), \
             patch("Services.verification_service.SpeechService.transcribe_audio", return_value=mock_transcription):
            audio = _generate_test_audio()
            client.post(
                "/api/v1/verify",
                data={"user_id": "test_user"},
                files={"audio_file": ("test.wav", audio, "audio/wav")},
            )

        # Second verify without a new challenge should fail with 400
        audio2 = _generate_test_audio()
        response = client.post(
            "/api/v1/verify",
            data={"user_id": "test_user"},
            files={"audio_file": ("test.wav", audio2, "audio/wav")},
        )
        assert response.status_code == 400

class TestVerifyRateLimit:
    """
    Tests for brute force protection via lockout-based rate limiting.

    The new rate limiter only counts FAILED attempts (wrong digits, voice
    mismatch, spoof, etc.) — not successful ones. To trigger a lockout,
    we feed wrong digits N times to force N failures.
    """

    def test_lockout_after_failed_attempts(self, client):
        from constants import MAX_FAILED_ATTEMPTS
        _enrol_test_user(client)

        wrong_digits = {
            "transcription": "00000",
            "normalized": "00000",
            "digits_only": "00000",
            "language": "en",
            "is_hallucination": False,
        }

        for _ in range(MAX_FAILED_ATTEMPTS):
            challenge = _generate_challenge_sync("test_user")
            # Guarantee the digits are wrong for this challenge
            wrong = "9" * len(challenge["challenge"])
            if wrong == challenge["challenge"]:
                wrong = "0" * len(challenge["challenge"])
            wrong_digits["digits_only"] = wrong

            with patch("Services.verification_service.AudioValidator.validate", return_value=MOCK_VALIDATOR), \
                 patch("Services.verification_service.SpoofingService.analyze_audio", return_value=MOCK_SPOOF), \
                 patch("Services.verification_service.SpeechService.transcribe_audio", return_value=wrong_digits):
                audio = _generate_test_audio()
                client.post(
                    "/api/v1/verify",
                    data={"user_id": "test_user"},
                    files={"audio_file": ("test.wav", audio, "audio/wav")},
                )

        # Next attempt should be blocked by the lockout (HTTP 429)
        _generate_challenge_sync("test_user")
        audio = _generate_test_audio()
        response = client.post(
            "/api/v1/verify",
            data={"user_id": "test_user"},
            files={"audio_file": ("test.wav", audio, "audio/wav")},
        )
        assert response.status_code == 429
        assert "lock" in response.json()["detail"].lower()

    def test_successful_verify_resets_counter(self, client):
        """A successful verification clears the failed attempt counter."""
        _enrol_test_user(client)

        # Record one failure manually
        asyncio.run(rate_limiter.record_failed_attempt("test_user"))
        assert rate_limiter.failed_counts.get("test_user") == 1

        # Now do a successful verification
        challenge = _generate_challenge_sync("test_user")
        mock_transcription = _mock_verify_transcription(challenge["challenge"])

        with patch("Services.verification_service.AudioValidator.validate", return_value=MOCK_VALIDATOR), \
             patch("Services.verification_service.SpoofingService.analyze_audio", return_value=MOCK_SPOOF), \
             patch("Services.verification_service.SpeechService.transcribe_audio", return_value=mock_transcription):
            audio = _generate_test_audio()
            client.post(
                "/api/v1/verify",
                data={"user_id": "test_user"},
                files={"audio_file": ("test.wav", audio, "audio/wav")},
            )

        # Counter should be cleared after success
        assert rate_limiter.failed_counts.get("test_user") is None