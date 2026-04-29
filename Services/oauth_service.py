# ===========================================================
# SpeakSecure — OAuth Service
# High-level API for OAuth 2.0 authorization code flow.
#
# Layered on top of AuthorizationCodeRepository:
#   - oauth_service handles code generation, TTL, dict shaping —
#     the business logic of the OAuth flow
#   - authorization_code_repository handles raw SQL inserts/selects
#
# Codes are opaque URL-safe strings with a 10-second TTL. They're
# single-use: once exchanged (via POST /token) they can't be reused.
# ===========================================================

import secrets
from datetime import datetime, timedelta, UTC
from typing import Optional

from constants import AUTHORIZATION_CODE_TTL_SECONDS
from Storage.authorization_code_repository import AuthorizationCodeRepository


class OAuthService:
    """Manages OAuth authorization codes for third-party integrations."""

    def __init__(self, code_repository: AuthorizationCodeRepository):
        self.repo = code_repository

    def create_authorization_code(
        self,
        user_id: str,
        verified: bool,
        api_key_id: int,
        redirect_uri: str,
        similarity_score: Optional[float],
        decision: str,
    ) -> dict:
        """
        Generate a new authorization code and persist it.

        Args:
            user_id: Which user was verified
            verified: Whether the verification succeeded
            api_key_id: Which API key initiated the /authorize call —
                        only this key will be able to exchange the code
            redirect_uri: The exact redirect_uri used during /authorize —
                          must match again at exchange
            similarity_score: Voice match score (None for spoof/rejected)
            decision: "accepted" / "rejected" / "retry"

        Returns:
            Dict with:
                code: The opaque code string to put in the redirect URL
                expires_at: ISO datetime when the code expires
                expires_in_seconds: TTL remaining (for convenience)
        """
        # 32 bytes → 43 chars of URL-safe base64. Plenty of entropy
        # to prevent brute-force; URL-safe so it works in query strings.
        code = secrets.token_urlsafe(32)

        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=AUTHORIZATION_CODE_TTL_SECONDS)
        expires_at_iso = expires_at.isoformat()

        self.repo.create(
            code=code,
            user_id=user_id,
            verified=verified,
            api_key_id=api_key_id,
            redirect_uri=redirect_uri,
            similarity_score=similarity_score,
            decision=decision,
            expires_at=expires_at_iso,
        )

        return {
            "code": code,
            "expires_at": expires_at_iso,
            "expires_in_seconds": AUTHORIZATION_CODE_TTL_SECONDS,
        }

    def exchange_code(
        self,
        code: str,
        api_key_id: int,
        redirect_uri: str,
    ) -> Optional[dict]:
        """
        Exchange an authorization code for the verification result.
        Called by POST /token. The code is marked as consumed atomically,
        so it can only be used once.

        Args:
            code: The code string the integrator is presenting
            api_key_id: The API key making this /token request.
                        MUST match the key that created the code.
            redirect_uri: The redirect_uri the integrator is claiming.
                          MUST match the one used during /authorize.

        Returns:
            Dict with verification details if all checks pass.
            None if the code was expired, unknown, already used,
            belongs to a different API key, or was issued for a
            different redirect_uri.
        """
        return self.repo.exchange(
            code=code,
            api_key_id=api_key_id,
            redirect_uri=redirect_uri,
        )

    def cleanup_expired(self) -> int:
        """
        Delete expired authorization codes from the database.
        Called by the periodic cleanup scheduler.
        """
        return self.repo.cleanup_expired()