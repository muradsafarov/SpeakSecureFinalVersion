# ===========================================================
# SpeakSecure — API Key Usage Repository
# Tracks how many requests each API key has made per hour.
# Used by the per-key rate limiter.
#
# DESIGN:
#   - One row per (api_key_id, hour_bucket). A "bucket" is an ISO
#     datetime truncated to the hour: "2026-04-21T15" means all
#     requests made during 15:00-15:59 UTC on 2026-04-21.
#   - Counter is updated atomically via SQL upsert (INSERT...ON CONFLICT)
#     so two concurrent requests cannot both slip past a limit.
#   - Rows older than a few days are deleted by the cleanup scheduler.
#     The schema includes an index on hour_bucket for this.
#
# WHY FIXED WINDOW (not sliding window / token bucket):
#   - Simpler and faster — a single upsert per request
#   - Predictable for integrators ("your limit resets at the top of
#     every hour")
#   - The trade-off is minor edge-case over-consumption at the hour
#     boundary, which is acceptable for FYP scope. Production-grade
#     systems like Stripe use token-bucket variants to smooth this.
# ===========================================================

from datetime import datetime, UTC, timedelta

from Storage.database import get_connection


def current_hour_bucket() -> str:
    """
    Return the current hour bucket key.
    Format: "YYYY-MM-DDTHH" (e.g. "2026-04-21T15" for 15:00-15:59 UTC).
    All usage in the same bucket increments the same DB row.
    """
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H")


class UsageRepository:
    """Atomic per-API-key request counters."""

    def increment_and_get(self, api_key_id: int, bucket: str) -> int:
        """
        Atomically increment this key's counter for the given hour bucket
        and return the new count.

        Uses SQLite's INSERT ... ON CONFLICT (upsert) so this is a single
        atomic operation — two concurrent requests cannot both read-then-
        write a stale value, which would let one sneak past a rate limit.

        Args:
            api_key_id: Database ID of the API key being used
            bucket:     Hour bucket string from current_hour_bucket()

        Returns:
            The new request count for this (key, bucket) combination.
        """
        with get_connection() as conn:
            # INSERT or INCREMENT in a single statement
            conn.execute(
                """
                INSERT INTO api_key_usage (api_key_id, hour_bucket, request_count)
                VALUES (?, ?, 1)
                ON CONFLICT(api_key_id, hour_bucket)
                DO UPDATE SET request_count = request_count + 1
                """,
                (api_key_id, bucket),
            )

            # Read back the resulting count
            row = conn.execute(
                """
                SELECT request_count FROM api_key_usage
                WHERE api_key_id = ? AND hour_bucket = ?
                """,
                (api_key_id, bucket),
            ).fetchone()

            return row["request_count"] if row else 0

    def cleanup_old(self, days_to_keep: int = 7) -> int:
        """
        Delete usage rows older than N days.
        Called by the periodic cleanup scheduler to keep the table small.
        We retain at least one week so recent usage history is available
        for debugging / simple reporting.

        Returns the number of rows deleted.
        """
        cutoff_time = datetime.now(UTC) - timedelta(days=days_to_keep)
        cutoff_bucket = cutoff_time.strftime("%Y-%m-%dT%H")

        with get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM api_key_usage WHERE hour_bucket < ?",
                (cutoff_bucket,),
            )
            return cursor.rowcount