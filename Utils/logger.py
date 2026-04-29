# ===========================================================
# SpeakSecure — Logger
# Structured logging using Loguru.
# Two outputs:
#   - Console: colored, INFO level (for development)
#   - File: detailed with rotation, DEBUG level (for audit trail)
# Log files stored in Data/Logs/speaksecure.log
# ===========================================================

import sys
from loguru import logger

from config import LOGS_DIR

def setup_logger():
    """
    Configure application-wide logging.
    Called once at startup in main.py.
    Returns the configured logger instance.
    """
    # Remove default Loguru handler to prevent duplicate output
    logger.remove()

    # Console output — colored, human-readable, INFO level only
    logger.add(
        sys.stdout,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> — "
            "<level>{message}</level>"
        ),
        level="INFO",
        colorize=True,
    )

    # File output — detailed with line numbers, auto-rotates at 5MB
    # Old logs compressed to .zip, kept for 7 days
    logger.add(
        LOGS_DIR / "speaksecure.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} — {message}",
        level="DEBUG",
        rotation="5 MB",
        retention="7 days",
        compression="zip",
    )

    logger.info("SpeakSecure logger initialized")

    return logger