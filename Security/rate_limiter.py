# ===========================================================
# SpeakSecure — Rate Limiters
#
# This file defines TWO rate limiters for different purposes:
#
# 1. RateLimiter (existing)
#    Per-USER lockout after too many consecutive failed voice
#    verifications. Protects against voice brute-force where an
#    attacker keeps trying different voice samples.
#
# 2. ApiKeyRateLimiter (new)
#    Per-API-KEY request budget per hour. Protects against integrator
#    abuse, runaway client loops, or a leaked/stolen API key.
#
# These limiters are independent — they protect against different
# threat models and use different storage:
#   - RateLimiter:        in-memory, per-user, failure-based
#   - ApiKeyRateLimiter:  SQLite-backed, per-key, total-request-based
# ===========================================================

import asyncio
from datetime import datetime, UTC, timedelta

from constants import MAX_FAILED_ATTEMPTS, LOCKOUT_DURATION_SECONDS
from Storage.usage_repository import UsageRepository, current_hour_bucket


class RateLimiter:
    """
    Per-user lockout after too many consecutive failed voice verifications.
    Protects against brute-force attacks where an attacker keeps trying
    different voice samples to find one that passes.
    """

    def __init__(self):
        # Count of failed attempts per user (resets on success or lockout expiry)
        self.failed_counts: dict[str, int] = {}
        # When each user's lockout expires (None/missing = not locked out)
        self.locked_until: dict[str, datetime] = {}
        # Lock prevents race conditions from concurrent verify requests
        self._lock = asyncio.Lock()

    async def is_allowed(self, user_id: str) -> bool:
        """
        Check if user is allowed to make a verification attempt.
        Returns False if the user is currently locked out.
        """
        async with self._lock:
            return not self._is_locked_out_nolock(user_id)

    async def record_failed_attempt(self, user_id: str) -> bool:
        """
        Record a failed verification attempt.
        If this brings the user up to MAX_FAILED_ATTEMPTS, trigger a lockout.
        Returns True if the user is now locked out, False otherwise.
        """
        async with self._lock:
            # Count the failure
            self.failed_counts[user_id] = self.failed_counts.get(user_id, 0) + 1

            # Trigger lockout if threshold reached
            if self.failed_counts[user_id] >= MAX_FAILED_ATTEMPTS:
                self.locked_until[user_id] = datetime.now(UTC) + timedelta(
                    seconds=LOCKOUT_DURATION_SECONDS
                )
                return True

            return False

    async def reset_attempts(self, user_id: str) -> None:
        """
        Clear the failure counter for a user.
        Called after a successful verification.
        """
        async with self._lock:
            self.failed_counts.pop(user_id, None)
            self.locked_until.pop(user_id, None)

    async def get_remaining_attempts(self, user_id: str) -> int:
        """
        Get how many failed attempts the user has left before lockout.
        Returns 0 if the user is currently locked out.
        """
        async with self._lock:
            if self._is_locked_out_nolock(user_id):
                return 0

            used = self.failed_counts.get(user_id, 0)
            return max(0, MAX_FAILED_ATTEMPTS - used)

    async def get_lockout_seconds_remaining(self, user_id: str) -> int:
        """
        Get seconds remaining until the user's lockout expires.
        Returns 0 if the user is not currently locked out.
        """
        async with self._lock:
            if not self._is_locked_out_nolock(user_id):
                return 0

            unlock_time = self.locked_until[user_id]
            remaining = (unlock_time - datetime.now(UTC)).total_seconds()
            return max(0, int(remaining))

    def _is_locked_out_nolock(self, user_id: str) -> bool:
        """
        Internal helper: check if user is currently locked out.
        Caller MUST hold self._lock before calling this method.
        Automatically clears expired lockouts.
        """
        if user_id not in self.locked_until:
            return False

        if datetime.now(UTC) >= self.locked_until[user_id]:
            # Lockout expired — reset the user's state entirely
            del self.locked_until[user_id]
            self.failed_counts.pop(user_id, None)
            return False

        return True


class ApiKeyRateLimiter:
    """
    Per-API-key hourly request budget.

    Each API key has a `rate_limit_per_hour` value stored in the database.
    For every authenticated request, we atomically increment that key's
    usage counter for the current hour; if the new count exceeds the
    limit, the request is rejected.

    Counter storage is SQLite — so counters survive server restarts
    (an attacker can't abuse a restart to reset the limit) and atomic
    upsert prevents two concurrent requests from both "just squeezing
    in" past the limit.
    """

    def __init__(self, usage_repository: UsageRepository):
        self.usage_repository = usage_repository

    def check_and_increment(
        self,
        api_key_id: int,
        limit_per_hour: int,
    ) -> tuple[bool, int, int]:
        """
        Atomically increment this key's counter for the current hour
        and decide whether the request is allowed.

        Returns:
            (allowed, current_count, limit) where:
            - allowed: True if the request is within the hourly budget
            - current_count: The new count after this request
            - limit: The hourly limit (echoed back for response headers)

        We increment EVEN IF the limit is exceeded. This is intentional:
        it ensures the counter reflects genuine attempted load, which
        is useful for monitoring and prevents subtle timing oracles
        (the response time should not depend on whether the limit was
        hit).
        """
        bucket = current_hour_bucket()
        current_count = self.usage_repository.increment_and_get(api_key_id, bucket)
        allowed = current_count <= limit_per_hour
        return allowed, current_count, limit_per_hour

    def cleanup_old(self, days_to_keep: int = 7) -> int:
        """
        Delete old usage rows. Called by the background cleanup scheduler.
        """
        return self.usage_repository.cleanup_old(days_to_keep=days_to_keep)