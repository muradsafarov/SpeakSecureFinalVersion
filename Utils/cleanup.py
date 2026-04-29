# ===========================================================
# SpeakSecure — Cleanup Utility
# Background task that periodically cleans up:
#   - Old temp audio files
#   - Expired OAuth authorization codes
#   - Old per-key rate-limit usage rows
# Runs automatically when the API starts via the lifespan handler.
# Default: every 10 minutes.
# Cleanup runs in a thread pool to avoid blocking the event loop.
# ===========================================================

import asyncio
from loguru import logger

from Services.audio_service import AudioService
from Services.oauth_service import OAuthService
from Security.rate_limiter import ApiKeyRateLimiter


class CleanupScheduler:
    """Periodically removes expired/old artefacts from disk and DB."""

    def __init__(
        self,
        audio_service: AudioService,
        oauth_service: OAuthService,
        api_key_rate_limiter: ApiKeyRateLimiter,
        interval_minutes: int = 10,
        max_file_age_minutes: int = 30,
        usage_retention_days: int = 7,
    ):
        self.audio_service = audio_service
        self.oauth_service = oauth_service
        self.api_key_rate_limiter = api_key_rate_limiter
        self.interval_minutes = interval_minutes
        self.max_file_age_minutes = max_file_age_minutes
        self.usage_retention_days = usage_retention_days
        self.running = False

    async def start(self) -> None:
        """Start the async cleanup loop. Runs until stop() is called."""
        self.running = True
        logger.info(
            f"Cleanup scheduler started — runs every {self.interval_minutes} min "
            f"(files > {self.max_file_age_minutes} min, "
            f"usage rows > {self.usage_retention_days} days)"
        )

        while self.running:
            # Wait for the configured interval before each cleanup pass
            await asyncio.sleep(self.interval_minutes * 60)

            # --- 1. Old temp audio files ---
            deleted_files = await asyncio.to_thread(
                self.audio_service.cleanup_old_files,
                self.max_file_age_minutes,
            )
            if deleted_files > 0:
                logger.info(f"Cleanup: deleted {deleted_files} old temp file(s)")

            # --- 2. Expired authorization codes (OAuth) ---
            try:
                deleted_codes = await asyncio.to_thread(
                    self.oauth_service.cleanup_expired,
                )
                if deleted_codes > 0:
                    logger.info(
                        f"Cleanup: deleted {deleted_codes} expired authorization code(s)"
                    )
            except Exception as e:
                logger.error(f"Authorization code cleanup failed: {e}")

            # --- 3. Old rate-limit usage rows ---
            try:
                deleted_usage = await asyncio.to_thread(
                    self.api_key_rate_limiter.cleanup_old,
                    self.usage_retention_days,
                )
                if deleted_usage > 0:
                    logger.info(f"Cleanup: deleted {deleted_usage} old usage row(s)")
            except Exception as e:
                logger.error(f"Usage cleanup failed: {e}")

    def stop(self) -> None:
        """Stop the cleanup loop gracefully."""
        self.running = False
        logger.info("Cleanup scheduler stopped")