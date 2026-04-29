# ===========================================================
# SpeakSecure — OAuth Service Tests
# Unit tests for the OAuth 2.0 authorization code service.
#
# These tests use a mocked AuthorizationCodeRepository — we're
# testing the service's BUSINESS LOGIC (code generation, TTL,
# argument shaping), not the SQL layer (which has its own tests
# at the integration level).
#
# Covers:
#   - Codes are URL-safe and have sufficient entropy
#   - Codes are unique across calls (collision probability ~ 0)
#   - TTL is propagated correctly from constants
#   - Repository is called with all the right binding fields
#     (user_id, api_key_id, redirect_uri) — these matter for security
#   - exchange_code is a thin pass-through (the security checks live
#     in the repository's atomic SELECT/UPDATE)
# ===========================================================

import pytest
from unittest.mock import MagicMock
from datetime import datetime, UTC

from Services.oauth_service import OAuthService
from constants import AUTHORIZATION_CODE_TTL_SECONDS


@pytest.fixture
def mock_repo():
    """A repository whose methods do nothing — we only inspect the calls."""
    repo = MagicMock()
    repo.create.return_value = None
    repo.exchange.return_value = None
    return repo


@pytest.fixture
def service(mock_repo):
    return OAuthService(code_repository=mock_repo)


class TestCreateAuthorizationCode:
    """Tests for code generation and persistence."""

    def test_returns_url_safe_code(self, service):
        """secrets.token_urlsafe produces base64url chars only — must
        survive being put in a redirect URL without escaping."""
        result = service.create_authorization_code(
            user_id="alice",
            verified=True,
            api_key_id=1,
            redirect_uri="http://shop.example/callback",
            similarity_score=0.85,
            decision="accepted",
        )
        code = result["code"]
        # URL-safe base64 alphabet: A-Z, a-z, 0-9, -, _
        allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
        assert all(c in allowed for c in code)

    def test_code_has_sufficient_entropy(self, service):
        """32 bytes → 43 base64url chars. We check the length to make sure
        no one accidentally reduces entropy by changing token_urlsafe args."""
        result = service.create_authorization_code(
            user_id="alice", verified=True, api_key_id=1,
            redirect_uri="http://shop.example/callback",
            similarity_score=None, decision="accepted",
        )
        # 32 bytes base64-encoded (no padding) = 43 chars
        assert len(result["code"]) >= 43

    def test_codes_are_unique_across_calls(self, service):
        """Two calls in quick succession must produce different codes —
        no shared state, no time-based predictability."""
        codes = set()
        for _ in range(20):
            r = service.create_authorization_code(
                user_id="alice", verified=True, api_key_id=1,
                redirect_uri="http://shop.example/callback",
                similarity_score=None, decision="accepted",
            )
            codes.add(r["code"])
        # All 20 codes should be unique
        assert len(codes) == 20

    def test_ttl_matches_constant(self, service):
        """The TTL value the caller sees must match the project constant —
        the integrator may rely on this for code-exchange timing."""
        result = service.create_authorization_code(
            user_id="alice", verified=True, api_key_id=1,
            redirect_uri="http://shop.example/callback",
            similarity_score=None, decision="accepted",
        )
        assert result["expires_in_seconds"] == AUTHORIZATION_CODE_TTL_SECONDS

    def test_expires_at_is_in_future(self, service):
        """Sanity: expires_at must be after now()."""
        result = service.create_authorization_code(
            user_id="alice", verified=True, api_key_id=1,
            redirect_uri="http://shop.example/callback",
            similarity_score=None, decision="accepted",
        )
        expires = datetime.fromisoformat(result["expires_at"])
        assert expires > datetime.now(UTC)

    def test_repo_called_with_all_binding_fields(self, service, mock_repo):
        """SECURITY: the repository must receive api_key_id and redirect_uri
        so the code can later be bound to that integrator at exchange time.
        If we drop either, an attacker with a different API key could steal
        the code."""
        service.create_authorization_code(
            user_id="alice",
            verified=True,
            api_key_id=42,
            redirect_uri="http://shop.example/callback",
            similarity_score=0.91,
            decision="accepted",
        )
        # The repository should have received exactly one create call
        mock_repo.create.assert_called_once()
        kwargs = mock_repo.create.call_args.kwargs
        assert kwargs["user_id"] == "alice"
        assert kwargs["verified"] is True
        assert kwargs["api_key_id"] == 42
        assert kwargs["redirect_uri"] == "http://shop.example/callback"
        assert kwargs["similarity_score"] == 0.91
        assert kwargs["decision"] == "accepted"

    def test_handles_unverified_codes(self, service, mock_repo):
        """Even rejected verifications get a code (so the integrator's
        callback fires and can show a 'try again' page) — but with
        verified=False so /token returns the rejection."""
        service.create_authorization_code(
            user_id="alice",
            verified=False,
            api_key_id=1,
            redirect_uri="http://shop.example/callback",
            similarity_score=None,
            decision="rejected",
        )
        kwargs = mock_repo.create.call_args.kwargs
        assert kwargs["verified"] is False
        assert kwargs["decision"] == "rejected"


class TestExchangeCode:
    """exchange_code is a thin wrapper — we just check the args pass through."""

    def test_exchange_passes_args_to_repo(self, service, mock_repo):
        service.exchange_code(
            code="abc123",
            api_key_id=42,
            redirect_uri="http://shop.example/callback",
        )
        mock_repo.exchange.assert_called_once_with(
            code="abc123",
            api_key_id=42,
            redirect_uri="http://shop.example/callback",
        )

    def test_exchange_returns_repo_result(self, service, mock_repo):
        """If the repository returns a dict, the service should return it
        unchanged — no transformation."""
        expected = {"verified": True, "user_id": "alice"}
        mock_repo.exchange.return_value = expected
        result = service.exchange_code(
            code="abc",
            api_key_id=1,
            redirect_uri="http://shop.example/callback",
        )
        assert result is expected

    def test_exchange_returns_none_when_repo_returns_none(self, service, mock_repo):
        """Repository returns None for unknown/expired/already-consumed
        codes. The service must propagate None — never invent a result."""
        mock_repo.exchange.return_value = None
        result = service.exchange_code(
            code="invalid",
            api_key_id=1,
            redirect_uri="http://shop.example/callback",
        )
        assert result is None


class TestCleanupExpired:
    """cleanup_expired is called by the background scheduler."""

    def test_cleanup_delegates_to_repo(self, service, mock_repo):
        mock_repo.cleanup_expired.return_value = 7
        result = service.cleanup_expired()
        mock_repo.cleanup_expired.assert_called_once()
        assert result == 7