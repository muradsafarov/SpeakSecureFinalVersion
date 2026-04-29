# ===========================================================
# SpeakSecure — Challenge Service Tests
# Unit tests for one-time challenge generation and verification.
# Async tests — service uses asyncio.Lock for thread safety.
# Tests cover: generation, matching, expiration, and one-time use.
# ===========================================================

import pytest
from datetime import datetime, timedelta, UTC

from Services.challenge_service import ChallengeService
from constants import CHALLENGE_LENGTH, CHALLENGE_EXPIRATION_SECONDS

@pytest.fixture
def service():
    return ChallengeService()

class TestGenerateChallenge:
    """Tests for challenge generation."""

    @pytest.mark.asyncio
    async def test_returns_correct_length(self, service):
        result = await service.generate_challenge("user1")
        assert len(result["challenge"]) == CHALLENGE_LENGTH

    @pytest.mark.asyncio
    async def test_contains_only_digits(self, service):
        result = await service.generate_challenge("user1")
        assert result["challenge"].isdigit()

    @pytest.mark.asyncio
    async def test_returns_correct_user_id(self, service):
        result = await service.generate_challenge("john")
        assert result["user_id"] == "john"

    @pytest.mark.asyncio
    async def test_returns_expiration(self, service):
        result = await service.generate_challenge("user1")
        assert result["expires_in_seconds"] == CHALLENGE_EXPIRATION_SECONDS

    @pytest.mark.asyncio
    async def test_overwrites_previous_challenge(self, service):
        """Generating a second challenge should replace the first one."""
        await service.generate_challenge("user1")
        second = await service.generate_challenge("user1")
        # The challenge stored internally should match the most recent one
        assert service.active_challenges["user1"]["challenge"] == second["challenge"]

class TestVerifyChallenge:
    """Tests for challenge verification."""

    @pytest.mark.asyncio
    async def test_correct_digits_pass(self, service):
        result = await service.generate_challenge("user1")
        challenge = result["challenge"]
        assert await service.verify_challenge("user1", challenge) is True

    @pytest.mark.asyncio
    async def test_wrong_digits_fail(self, service):
        await service.generate_challenge("user1")
        assert await service.verify_challenge("user1", "00000") is False

    @pytest.mark.asyncio
    async def test_challenge_consumed_after_verify(self, service):
        # Challenge is one-time use — second attempt must fail
        result = await service.generate_challenge("user1")
        challenge = result["challenge"]
        await service.verify_challenge("user1", challenge)
        assert await service.verify_challenge("user1", challenge) is False

    @pytest.mark.asyncio
    async def test_no_challenge_returns_false(self, service):
        assert await service.verify_challenge("unknown_user", "12345") is False

    @pytest.mark.asyncio
    async def test_expired_challenge_fails(self, service):
        await service.generate_challenge("user1")
        # Manually expire the challenge
        service.active_challenges["user1"]["expires_at"] = (
            datetime.now(UTC) - timedelta(seconds=1)
        )
        assert await service.verify_challenge("user1", "12345") is False

class TestHasActiveChallenge:
    """Tests for checking active challenge status."""

    @pytest.mark.asyncio
    async def test_active_challenge_exists(self, service):
        await service.generate_challenge("user1")
        assert await service.has_active_challenge("user1") is True

    @pytest.mark.asyncio
    async def test_no_challenge_for_user(self, service):
        assert await service.has_active_challenge("unknown") is False

    @pytest.mark.asyncio
    async def test_expired_challenge_not_active(self, service):
        await service.generate_challenge("user1")
        service.active_challenges["user1"]["expires_at"] = (
            datetime.now(UTC) - timedelta(seconds=1)
        )
        assert await service.has_active_challenge("user1") is False

    @pytest.mark.asyncio
    async def test_consumed_challenge_not_active(self, service):
        result = await service.generate_challenge("user1")
        await service.verify_challenge("user1", result["challenge"])
        assert await service.has_active_challenge("user1") is False