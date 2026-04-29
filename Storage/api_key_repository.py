# ===========================================================
# SpeakSecure — API Key Repository
# Database operations for API keys:
#   - create:                  insert a new key record
#   - find_by_hash:            look up a key by its hash (used on every request)
#   - find_by_id:              look up a key by its database ID
#   - list_all:                list all keys (for admin/CLI)
#   - revoke:                  mark a key as revoked without deleting its history
#   - is_redirect_uri_allowed: validate redirect_uri during /authorize
#
# All methods operate on the api_keys table defined in database.py.
# Keys are stored as SHA-256 hashes; plaintext keys never touch the DB.
# ===========================================================

import json
from datetime import datetime, UTC
from typing import Optional

from Storage.database import get_connection


class ApiKeyRepository:
    """Database-backed storage for API keys."""

    def create(
        self,
        key_hash: str,
        key_prefix: str,
        name: str,
        origins: list[str],
        redirect_uris: list[str],
        rate_limit_per_hour: int = 1000,
    ) -> int:
        """
        Insert a new API key record.
        The caller must hash the plaintext key before calling this method —
        this repository never sees plaintext keys.

        Args:
            key_hash: SHA-256 hash of the plaintext key
            key_prefix: First 12 chars of the plaintext key (for display only)
            name: Human-readable name, e.g. "Acme Shop Production"
            origins: Allowed origins for direct API calls
                     (e.g. ["https://acme.com"]). Empty list = any origin.
            redirect_uris: Allowed redirect URIs for the OAuth flow
                           (e.g. ["https://acme.com/callback"]).
                           These are validated during GET /authorize so that
                           an attacker cannot redirect users to evil.com.
                           Empty list = key cannot use OAuth flow.
            rate_limit_per_hour: Maximum requests per hour for this key.

        Returns:
            The database ID of the new key.
        """
        origins_json = json.dumps(origins)
        redirect_uris_json = json.dumps(redirect_uris)
        now = datetime.now(UTC).isoformat()

        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO api_keys
                    (key_hash, key_prefix, name, origins, redirect_uris,
                     rate_limit_per_hour, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key_hash, key_prefix, name,
                    origins_json, redirect_uris_json,
                    rate_limit_per_hour, now,
                ),
            )
            return cursor.lastrowid

    def find_by_hash(self, key_hash: str) -> Optional[dict]:
        """
        Look up an API key by its hash.
        Used on every API request (via the require_api_key dependency).

        Returns a dict with key metadata, or None if the hash is unknown
        or the key has been revoked.
        """
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT id, key_hash, key_prefix, name, origins, redirect_uris,
                       rate_limit_per_hour, created_at, revoked_at
                FROM api_keys
                WHERE key_hash = ? AND revoked_at IS NULL
                """,
                (key_hash,),
            ).fetchone()

        if row is None:
            return None

        return self._row_to_dict(row)

    def find_by_id(self, key_id: int) -> Optional[dict]:
        """
        Look up an API key by its database ID.
        Useful for any admin or diagnostic endpoint.
        """
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT id, key_hash, key_prefix, name, origins, redirect_uris,
                       rate_limit_per_hour, created_at, revoked_at
                FROM api_keys
                WHERE id = ? AND revoked_at IS NULL
                """,
                (key_id,),
            ).fetchone()

        if row is None:
            return None

        return self._row_to_dict(row)

    def list_all(self, include_revoked: bool = False) -> list[dict]:
        """
        List all API keys, most recent first.
        Used by the CLI for admin visibility.
        """
        query = """
            SELECT id, key_hash, key_prefix, name, origins, redirect_uris,
                   rate_limit_per_hour, created_at, revoked_at
            FROM api_keys
        """
        if not include_revoked:
            query += " WHERE revoked_at IS NULL"
        query += " ORDER BY created_at DESC"

        with get_connection() as conn:
            rows = conn.execute(query).fetchall()

        return [self._row_to_dict(row) for row in rows]

    def revoke(self, key_id: int) -> bool:
        """
        Mark a key as revoked. It will immediately stop working but its
        history (usage counts) is preserved for audit.

        Returns True if the key was found and revoked, False otherwise.
        """
        now = datetime.now(UTC).isoformat()

        with get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE api_keys
                SET revoked_at = ?
                WHERE id = ? AND revoked_at IS NULL
                """,
                (now, key_id),
            )
            return cursor.rowcount > 0

    def is_redirect_uri_allowed(self, key_id: int, redirect_uri: str) -> bool:
        """
        Check whether a given redirect URI is in the whitelist for this key.

        This is THE critical security check for the OAuth /authorize flow.
        Without it, an attacker can craft a phishing link:
            /authorize?client_id=acme&redirect_uri=https://evil.com&state=x
        and steal the user's authorization code.

        We require an EXACT MATCH (case-sensitive, including trailing slash)
        to follow OAuth 2.0 best current practices. No subdomain wildcards,
        no path prefixes — the integrator must register every URI they use.
        """
        with get_connection() as conn:
            row = conn.execute(
                "SELECT redirect_uris FROM api_keys WHERE id = ? AND revoked_at IS NULL",
                (key_id,),
            ).fetchone()

        if row is None:
            return False

        try:
            allowed = json.loads(row["redirect_uris"])
        except (TypeError, ValueError):
            return False

        return redirect_uri in allowed

    def _row_to_dict(self, row) -> dict:
        """Convert a sqlite3.Row into a clean Python dict with parsed JSON fields."""
        return {
            "id": row["id"],
            "key_hash": row["key_hash"],
            "key_prefix": row["key_prefix"],
            "name": row["name"],
            "origins": json.loads(row["origins"]),
            "redirect_uris": json.loads(row["redirect_uris"]),
            "rate_limit_per_hour": row["rate_limit_per_hour"],
            "created_at": row["created_at"],
            "revoked_at": row["revoked_at"],
        }