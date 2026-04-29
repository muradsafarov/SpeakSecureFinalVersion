# ===========================================================
# SpeakSecure — SQLite Database
# Central database connection and schema management.
#
# WHY SQLITE (and not JSON/dict):
#   - Transactional: atomic writes, no race conditions on concurrent
#     API key creation or authorization code consumption
#   - Survives server restarts (in-memory state would be lost)
#   - No external dependencies — part of Python stdlib
#   - Fast enough for FYP scale; production would use Postgres
#
# The database file is created automatically on first run.
# Schema migrations are applied idempotently at startup.
# ===========================================================

import sqlite3
from contextlib import contextmanager

# Import from config_paths (torch-free) instead of config — keeps the
# Storage layer importable without ML dependencies. See config_paths.py.
from config_paths import DATABASE_PATH


# --- SQL schema ---
# These CREATE statements use IF NOT EXISTS so they can be run on every
# startup safely. This is a simple form of schema migration that's
# appropriate for a project of this size.
SCHEMA = """
-- API keys issued for self-service or third-party integrations.
-- Keys are stored as SHA-256 hashes, never plaintext.
-- redirect_uris is a JSON array of allowed callback URLs for OAuth flow.
-- For self-service keys (no OAuth), redirect_uris is just '[]'.
CREATE TABLE IF NOT EXISTS api_keys (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash            TEXT NOT NULL UNIQUE,
    key_prefix          TEXT NOT NULL,
    name                TEXT NOT NULL,
    origins             TEXT NOT NULL,
    redirect_uris       TEXT NOT NULL DEFAULT '[]',
    rate_limit_per_hour INTEGER NOT NULL DEFAULT 1000,
    created_at          TEXT NOT NULL,
    revoked_at          TEXT
);

CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);

-- Authorization codes issued by GET /authorize after a successful
-- voice verification. Third-party backends exchange them for the
-- verification result via POST /token.
--
-- This is the authorization_code grant from RFC 6749 (OAuth 2.0).
-- Codes are very short-lived (10 seconds) because they only need to
-- survive the round-trip from our /authorize redirect → integrator's
-- /callback → integrator's backend → our POST /token.
CREATE TABLE IF NOT EXISTS authorization_codes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    code              TEXT NOT NULL UNIQUE,
    user_id           TEXT NOT NULL,
    verified          INTEGER NOT NULL,
    api_key_id        INTEGER NOT NULL,
    redirect_uri      TEXT NOT NULL,
    similarity_score  REAL,
    decision          TEXT,
    created_at        TEXT NOT NULL,
    expires_at        TEXT NOT NULL,
    consumed_at       TEXT,
    FOREIGN KEY (api_key_id) REFERENCES api_keys(id)
);

CREATE INDEX IF NOT EXISTS idx_codes_code ON authorization_codes(code);
CREATE INDEX IF NOT EXISTS idx_codes_expires ON authorization_codes(expires_at);

-- Per-API-key request counts for rate limiting.
-- One row per (api_key_id, hour_bucket); incremented atomically.
CREATE TABLE IF NOT EXISTS api_key_usage (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_id   INTEGER NOT NULL,
    hour_bucket  TEXT NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (api_key_id) REFERENCES api_keys(id),
    UNIQUE(api_key_id, hour_bucket)
);

CREATE INDEX IF NOT EXISTS idx_usage_bucket ON api_key_usage(api_key_id, hour_bucket);
"""


def init_database() -> None:
    """
    Create the database file and apply the schema.
    Called once at server startup. Safe to call multiple times because
    CREATE IF NOT EXISTS is idempotent.
    """
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def get_connection():
    """
    Context manager that opens a SQLite connection and returns rows as dicts.

    Usage:
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (1,)).fetchone()
            # row["name"] works like a dict

    Foreign keys are enabled per-connection (SQLite default is OFF).
    """
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row  # enables dict-style access: row["name"]
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()