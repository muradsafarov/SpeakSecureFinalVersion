# ===========================================================
# SpeakSecure — Challenge Service
# Generates one-time digit challenges with TTL expiration.
# Core replay attack protection mechanism:
# - Each challenge is random and unique
# - Expires after 60 seconds
# - Can only be used once (consumed on verification)
# - Thread-safe via asyncio.Lock for concurrent request protection
# ===========================================================

import asyncio
import random
from datetime import datetime, timedelta, UTC

from constants import CHALLENGE_LENGTH, CHALLENGE_EXPIRATION_SECONDS

class ChallengeService:
    """Manages one-time voice challenges for replay attack protection."""

    def __init__(self):
        # In-memory store: user_id → {challenge, expires_at}
        # One-time use is enforced by deleting the entry on verify,
        # so no explicit "used" flag is needed.
        self.active_challenges: dict[str, dict] = {}
        # Lock prevents race conditions from concurrent verify requests
        self._lock = asyncio.Lock()

    async def generate_challenge(self, user_id: str) -> dict:
        """
        Generate a new random digit challenge for a user.
        Any existing challenge for this user is overwritten.
        """
        # Basic input validation (defence in depth — route layer also validates)
        if not user_id or not user_id.strip():
            raise ValueError("Cannot generate challenge: user_id is empty.")

        async with self._lock:
            # Housekeeping: remove expired challenges to prevent memory leaks
            self._cleanup_expired()

            # Generate random digits (e.g. "73829")
            challenge = "".join(
                str(random.randint(0, 9)) for _ in range(CHALLENGE_LENGTH)
            )

            expires_at = datetime.now(UTC) + timedelta(
                seconds=CHALLENGE_EXPIRATION_SECONDS
            )

            self.active_challenges[user_id] = {
                "challenge": challenge,
                "expires_at": expires_at,
            }

            return {
                "user_id": user_id,
                "challenge": challenge,
                "expires_in_seconds": CHALLENGE_EXPIRATION_SECONDS,
                "message": (
                    f"Challenge generated for user '{user_id}'. "
                    f"Speak the digits to verify."
                ),
            }

    async def verify_challenge(self, user_id: str, spoken_digits: str) -> bool:
        """
        Verify spoken digits against the active challenge.
        The challenge is always consumed (deleted) after this call,
        regardless of whether the digits match — this guarantees one-time
        use and prevents replay attacks.
        Thread-safe: only one concurrent caller can consume a challenge.
        """
        async with self._lock:
            challenge_data = self.active_challenges.pop(user_id, None)

            if challenge_data is None:
                return False

            # Reject if expired (TTL protection)
            if datetime.now(UTC) > challenge_data["expires_at"]:
                return False

            return spoken_digits == challenge_data["challenge"]

    async def has_active_challenge(self, user_id: str) -> bool:
        """Check if user has a valid, non-expired challenge."""
        async with self._lock:
            challenge_data = self.active_challenges.get(user_id)
            if challenge_data is None:
                return False

            # Lazily clean up if expired
            if datetime.now(UTC) > challenge_data["expires_at"]:
                del self.active_challenges[user_id]
                return False

            return True

    def _cleanup_expired(self) -> None:
        """
        Remove all expired challenges from memory.
        Internal helper — caller must hold the lock.
        """
        now = datetime.now(UTC)
        expired_users = [
            uid for uid, data in self.active_challenges.items()
            if now > data["expires_at"]
        ]
        for uid in expired_users:
            del self.active_challenges[uid]