# ===========================================================
# SpeakSecure — Enrolment Tests
# Integration tests for the /enrol endpoints via FastAPI TestClient.
# Pipeline tests mock AudioValidator and SpoofingService since
# synthetic audio won't pass speech detection or anti-spoofing.
#
# Covers:
#   - First-time registration (POST /enrol)
#   - Duplicate username rejection (409 Conflict)
#   - Adding samples to an existing user (POST /enrol/add-sample)
#   - Sample limit enforcement
#   - Username availability check (GET /enrol/check)
# ===========================================================

import io
import pytest
import torch
import torchaudio
from unittest.mock import patch
from fastapi.testclient import TestClient

from main import app
from constants import MAX_SAMPLES_PER_USER
from Services.dependencies import voiceprint_repository

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture(autouse=True)
def cleanup_after_test():
    """Remove test user data after each test to prevent state leaking."""
    yield
    voiceprint_repository.delete_user("test_user")

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
# Shape must match what the service code reads from these functions.
MOCK_VALIDATOR = {"is_valid": True, "checks": {}, "message": "ok"}
MOCK_SPOOF = {
    "spoof_detected": False,
    "confidence": 0.1,
    "label": "bonafide",
    "threshold_used": 0.5,
}
MOCK_TRANSCRIPTION = {
    "transcription": "hello",
    "normalized": "hello",
    "digits_only": "",
    "language": "en",
    "is_hallucination": False,
}

def _enrol(client, user_id: str = "test_user"):
    """Helper: enrol a user with mocked validation. Returns response."""
    with patch("Services.enrolment_service.AudioValidator.validate", return_value=MOCK_VALIDATOR), \
         patch("Services.enrolment_service.SpoofingService.analyze_audio", return_value=MOCK_SPOOF), \
         patch("Services.enrolment_service.SpeechService.transcribe_audio", return_value=MOCK_TRANSCRIPTION):
        audio = _generate_test_audio()
        return client.post(
            "/api/v1/enrol",
            data={"user_id": user_id},
            files={"audio_file": ("test.wav", audio, "audio/wav")},
        )

def _add_sample(client, user_id: str = "test_user"):
    """Helper: add an additional sample with mocked validation."""
    with patch("Services.enrolment_service.AudioValidator.validate", return_value=MOCK_VALIDATOR), \
         patch("Services.enrolment_service.SpoofingService.analyze_audio", return_value=MOCK_SPOOF), \
         patch("Services.enrolment_service.SpeechService.transcribe_audio", return_value=MOCK_TRANSCRIPTION):
        audio = _generate_test_audio()
        return client.post(
            "/api/v1/enrol/add-sample",
            data={"user_id": user_id},
            files={"audio_file": ("test.wav", audio, "audio/wav")},
        )

# ==================== POST /enrol ====================

class TestEnrolNewUser:
    """Tests for first-time user registration."""

    def test_enrol_new_user_succeeds(self, client):
        response = _enrol(client)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["user_id"] == "test_user"
        assert data["num_samples"] == 1
        assert data["max_samples"] == MAX_SAMPLES_PER_USER

    def test_user_exists_after_enrolment(self, client):
        _enrol(client)
        assert voiceprint_repository.user_exists("test_user") is True

    def test_duplicate_username_rejected(self, client):
        """Re-enrolling the same username must fail with 409 Conflict."""
        _enrol(client)
        response = _enrol(client)
        assert response.status_code == 409
        assert "already taken" in response.json()["detail"].lower()

class TestEnrolValidation:
    """Tests for enrolment input validation and error handling."""

    def test_missing_audio(self, client):
        response = client.post(
            "/api/v1/enrol",
            data={"user_id": "test_user"},
        )
        assert response.status_code == 422

    def test_missing_user_id(self, client):
        audio = _generate_test_audio()
        response = client.post(
            "/api/v1/enrol",
            files={"audio_file": ("test.wav", audio, "audio/wav")},
        )
        assert response.status_code == 422

    def test_unsupported_format(self, client):
        fake_file = io.BytesIO(b"not real audio")
        response = client.post(
            "/api/v1/enrol",
            data={"user_id": "test_user"},
            files={"audio_file": ("test.txt", fake_file, "text/plain")},
        )
        assert response.status_code == 400

# ==================== POST /enrol/add-sample ====================

class TestAddSample:
    """Tests for adding additional voice samples to an existing user."""

    def test_add_sample_to_existing_user(self, client):
        """First enrol creates the user, then add-sample appends one more."""
        _enrol(client)
        response = _add_sample(client)

        assert response.status_code == 200
        data = response.json()
        assert data["num_samples"] == 2
        assert data["max_samples"] == MAX_SAMPLES_PER_USER

    def test_add_sample_to_nonexistent_user_fails(self, client):
        """Cannot add a sample to a user that doesn't exist (404)."""
        response = _add_sample(client, user_id="ghost_user")
        assert response.status_code == 404

    def test_sample_limit_enforced(self, client):
        """Once MAX_SAMPLES_PER_USER reached, further adds must fail."""
        _enrol(client)  # 1 sample
        # Fill up to the limit
        for _ in range(MAX_SAMPLES_PER_USER - 1):
            _add_sample(client)

        # One more should be rejected
        response = _add_sample(client)
        assert response.status_code == 400
        assert "maximum" in response.json()["detail"].lower()

# ==================== GET /enrol/check/{user_id} ====================

class TestCheckUsername:
    """Tests for the username availability check endpoint."""

    def test_check_unknown_user(self, client):
        """Unknown user should report exists=False."""
        response = client.get("/api/v1/enrol/check/unknown_user_12345")
        assert response.status_code == 200
        data = response.json()
        assert data["exists"] is False
        assert data["num_samples"] == 0
        assert data["can_add_sample"] is False

    def test_check_existing_user(self, client):
        """Enrolled user should report exists=True with sample count."""
        _enrol(client)
        response = client.get("/api/v1/enrol/check/test_user")
        assert response.status_code == 200
        data = response.json()
        assert data["exists"] is True
        assert data["num_samples"] == 1
        assert data["max_samples"] == MAX_SAMPLES_PER_USER
        assert data["can_add_sample"] is True

    def test_check_user_at_limit(self, client):
        """User who reached the sample limit should have can_add_sample=False."""
        _enrol(client)
        for _ in range(MAX_SAMPLES_PER_USER - 1):
            _add_sample(client)

        response = client.get("/api/v1/enrol/check/test_user")
        data = response.json()
        assert data["num_samples"] == MAX_SAMPLES_PER_USER
        assert data["can_add_sample"] is False