# ===========================================================
# SpeakSecure — Rate Limiter Tests
# Unit tests for the per-user lockout rate limiter.
#
# Covers the security-critical paths:
#   - Lockout triggers exactly at MAX_FAILED_ATTEMPTS (off-by-one safety)
#   - Successful verification resets the counter
#   - Lockout expires after LOCKOUT_DURATION_SECONDS
#   - Concurrent failed attempts increment safely under asyncio.Lock
#   - Independent users have independent counters
# ===========================================================

import asyncio
import pytest
from datetime import datetime, timedelta, UTC

from Security.rate_limiter import RateLimiter
from constants import MAX_FAILED_ATTEMPTS


@pytest.fixture
def limiter():
    """Fresh limiter for each test — no shared state across tests."""
    return RateLimiter()


class TestIsAllowed:
    """A user starts with a clean slate and is allowed by default."""

    @pytest.mark.asyncio
    async def test_new_user_is_allowed(self, limiter):
        assert await limiter.is_allowed("alice") is True

    @pytest.mark.asyncio
    async def test_user_under_limit_is_allowed(self, limiter):
        # Record a few failures, but stay under the limit
        for _ in range(MAX_FAILED_ATTEMPTS - 1):
            await limiter.record_failed_attempt("alice")
        assert await limiter.is_allowed("alice") is True


class TestLockout:
    """Lockout is the security-critical path — these tests must be tight."""

    @pytest.mark.asyncio
    async def test_lockout_triggers_at_exact_threshold(self, limiter):
        """The Nth failure (where N = MAX_FAILED_ATTEMPTS) should trigger lockout."""
        # First N-1 failures should not trigger lockout
        for _ in range(MAX_FAILED_ATTEMPTS - 1):
            triggered = await limiter.record_failed_attempt("alice")
            assert triggered is False
        # The Nth failure triggers it
        triggered = await limiter.record_failed_attempt("alice")
        assert triggered is True
        assert await limiter.is_allowed("alice") is False

    @pytest.mark.asyncio
    async def test_remaining_attempts_decreases_with_each_failure(self, limiter):
        # Start with full quota
        assert await limiter.get_remaining_attempts("alice") == MAX_FAILED_ATTEMPTS
        await limiter.record_failed_attempt("alice")
        assert await limiter.get_remaining_attempts("alice") == MAX_FAILED_ATTEMPTS - 1

    @pytest.mark.asyncio
    async def test_remaining_attempts_zero_when_locked_out(self, limiter):
        for _ in range(MAX_FAILED_ATTEMPTS):
            await limiter.record_failed_attempt("alice")
        assert await limiter.get_remaining_attempts("alice") == 0

    @pytest.mark.asyncio
    async def test_get_lockout_seconds_zero_when_not_locked(self, limiter):
        assert await limiter.get_lockout_seconds_remaining("alice") == 0


class TestReset:
    """Successful verification clears all failure state."""

    @pytest.mark.asyncio
    async def test_reset_clears_failure_count(self, limiter):
        # Build up some failures
        for _ in range(MAX_FAILED_ATTEMPTS - 1):
            await limiter.record_failed_attempt("alice")
        # Reset (simulating a successful verify)
        await limiter.reset_attempts("alice")
        # Counter is back to full
        assert await limiter.get_remaining_attempts("alice") == MAX_FAILED_ATTEMPTS

    @pytest.mark.asyncio
    async def test_reset_unlocks_locked_user(self, limiter):
        # Trip the lockout
        for _ in range(MAX_FAILED_ATTEMPTS):
            await limiter.record_failed_attempt("alice")
        assert await limiter.is_allowed("alice") is False
        # Reset (e.g. admin action) clears the lockout
        await limiter.reset_attempts("alice")
        assert await limiter.is_allowed("alice") is True


class TestLockoutExpiry:
    """Lockout should auto-expire after LOCKOUT_DURATION_SECONDS."""

    @pytest.mark.asyncio
    async def test_expired_lockout_auto_clears(self, limiter):
        """When the lockout window has passed, the user is allowed again
        without any explicit reset call."""
        # Trip lockout
        for _ in range(MAX_FAILED_ATTEMPTS):
            await limiter.record_failed_attempt("alice")
        assert await limiter.is_allowed("alice") is False

        # Manually backdate the lockout to simulate time passing.
        # We mutate locked_until directly because waiting LOCKOUT_DURATION_SECONDS
        # in a unit test would be slow (60+ seconds).
        limiter.locked_until["alice"] = datetime.now(UTC) - timedelta(seconds=1)

        # The next is_allowed call should detect the expiry, clear state,
        # and return True.
        assert await limiter.is_allowed("alice") is True
        # State should be fully reset — counter back to full
        assert await limiter.get_remaining_attempts("alice") == MAX_FAILED_ATTEMPTS


class TestUserIsolation:
    """One user's failures must NOT affect another user's quota."""

    @pytest.mark.asyncio
    async def test_users_have_independent_counters(self, limiter):
        # Trip alice's lockout
        for _ in range(MAX_FAILED_ATTEMPTS):
            await limiter.record_failed_attempt("alice")
        # Bob should be completely unaffected
        assert await limiter.is_allowed("bob") is True
        assert await limiter.get_remaining_attempts("bob") == MAX_FAILED_ATTEMPTS


class TestConcurrency:
    """The limiter uses asyncio.Lock — concurrent failures must not race
    past each other and double-count or skip the threshold."""

    @pytest.mark.asyncio
    async def test_concurrent_failures_count_correctly(self, limiter):
        """Fire MAX_FAILED_ATTEMPTS failures concurrently. The counter
        should still reach exactly MAX_FAILED_ATTEMPTS — not less due to
        a lost update, not more due to double-counting."""
        # Issue all failures at once
        await asyncio.gather(*[
            limiter.record_failed_attempt("alice")
            for _ in range(MAX_FAILED_ATTEMPTS)
        ])
        # User is locked, with exactly 0 remaining
        assert await limiter.is_allowed("alice") is False
        assert await limiter.get_remaining_attempts("alice") == 0