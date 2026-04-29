# ===========================================================
# SpeakSecure — Audio Service
# Handles saving uploaded audio files to temp storage,
# converting to WAV format, and cleaning up old files.
# Supports browser formats (WebM) via ffmpeg conversion.
# ===========================================================

import subprocess
from pathlib import Path
from uuid import uuid4
from datetime import datetime, UTC, timedelta

from fastapi import UploadFile
from loguru import logger

from config import TEMP_AUDIO_DIR
from constants import ALLOWED_AUDIO_EXTENSIONS

# Browser recording formats that need ffmpeg conversion to WAV.
# Overlaps with ALLOWED_AUDIO_EXTENSIONS — the set union below
# automatically de-duplicates.
BROWSER_FORMATS = {".webm", ".ogg", ".mp4", ".m4a", ".mp3", ".aac", ".flac"}

# All extensions the API will accept on upload
ALL_ALLOWED_EXTENSIONS = ALLOWED_AUDIO_EXTENSIONS | BROWSER_FORMATS

# FFmpeg conversion timeout — defined in constants.py for single source
# of truth. Must be longer than expected conversion time for 15-second
# audio (typical: 1-3 seconds).
from constants import FFMPEG_TIMEOUT_SECONDS

class AudioService:
    """Manages temporary audio file storage and format conversion."""

    def __init__(self):
        self.temp_dir = TEMP_AUDIO_DIR
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    async def save_temp_audio(self, audio_file: UploadFile) -> str:
        """
        Save uploaded audio file to temp directory.
        Non-WAV formats are automatically converted via ffmpeg.
        """
        if not audio_file.filename:
            raise ValueError("Uploaded file must have a filename.")

        extension = Path(audio_file.filename).suffix.lower()

        if extension not in ALL_ALLOWED_EXTENSIONS:
            raise ValueError(
                f"Unsupported audio format: '{extension}'. "
                f"Allowed: {', '.join(sorted(ALL_ALLOWED_EXTENSIONS))}"
            )

        # Generate unique filename to prevent collisions
        unique_name = f"{uuid4().hex}{extension}"
        original_path = self.temp_dir / unique_name

        file_bytes = await audio_file.read()

        if not file_bytes:
            raise ValueError("Uploaded audio file is empty.")

        with open(original_path, "wb") as f:
            f.write(file_bytes)

        # Convert non-WAV formats to WAV using ffmpeg
        if extension != ".wav":
            wav_path = original_path.with_suffix(".wav")
            try:
                self._convert_to_wav(str(original_path), str(wav_path))
            except Exception:
                # Always clean up the original file if conversion fails
                original_path.unlink(missing_ok=True)
                raise

            # Remove original, keep only the WAV version
            original_path.unlink(missing_ok=True)
            return str(wav_path)

        return str(original_path)

    def _convert_to_wav(self, input_path: str, output_path: str) -> None:
        """
        Convert any audio format to 16kHz mono WAV using ffmpeg.
        Uses PCM 32-bit float to preserve quality for AASIST analysis.
        Falls back to default resampler if soxr is not available.
        Raises ValueError on failure (caught by caller).
        """
        # Primary: high-quality conversion with soxr resampler
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", input_path,
                    "-vn",                          # Strip video stream
                    "-acodec", "pcm_f32le",          # 32-bit float PCM
                    "-ar", "16000",                  # Resample to 16kHz
                    "-ac", "1",                      # Convert to mono
                    "-af", "aresample=resampler=soxr",
                    output_path,
                ],
                capture_output=True,
                text=True,
                timeout=FFMPEG_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            logger.error(f"FFmpeg timeout after {FFMPEG_TIMEOUT_SECONDS}s (primary)")
            raise ValueError(
                f"Audio conversion timed out after {FFMPEG_TIMEOUT_SECONDS} seconds. "
                f"The audio file may be corrupted or too complex to process."
            )
        except FileNotFoundError:
            # ffmpeg binary not installed on system
            logger.error("FFmpeg binary not found — is ffmpeg installed?")
            raise ValueError(
                "Audio conversion failed: ffmpeg is not installed on the server."
            )

        if result.returncode != 0:
            # Fallback: convert without soxr resampler (may not be available)
            try:
                result = subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-i", input_path,
                        "-vn",
                        "-acodec", "pcm_f32le",
                        "-ar", "16000",
                        "-ac", "1",
                        output_path,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=FFMPEG_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired:
                logger.error(f"FFmpeg timeout after {FFMPEG_TIMEOUT_SECONDS}s (fallback)")
                raise ValueError(
                    f"Audio conversion timed out after {FFMPEG_TIMEOUT_SECONDS} seconds. "
                    f"The audio file may be corrupted."
                )

            if result.returncode != 0:
                logger.error(f"FFmpeg conversion failed: {result.stderr[:200]}")
                raise ValueError(
                    "Audio conversion failed. The file may be corrupted or "
                    "in an unsupported format."
                )

    def cleanup_old_files(self, max_age_minutes: int = 30) -> int:
        """
        Delete temp audio files older than max_age_minutes.
        Called periodically by the CleanupScheduler.
        Resilient to race conditions: files may be deleted by other
        processes between iterdir() and unlink().
        """
        cutoff = datetime.now(UTC) - timedelta(minutes=max_age_minutes)
        deleted = 0

        # Wrap entire loop in try/except to prevent scheduler crashes
        try:
            for file in self.temp_dir.iterdir():
                try:
                    # File may have been deleted between iterdir() and now
                    if not file.is_file():
                        continue

                    file_modified = datetime.fromtimestamp(
                        file.stat().st_mtime, tz=UTC
                    )

                    if file_modified < cutoff:
                        file.unlink()
                        deleted += 1

                except FileNotFoundError:
                    # File was deleted by another process — skip it
                    continue
                except PermissionError as e:
                    # File locked by another process — log and skip
                    logger.warning(f"Cannot delete {file.name}: {e}")
                    continue
                except Exception as e:
                    # Unexpected error on a single file — log and continue
                    logger.warning(f"Error processing {file.name}: {e}")
                    continue

        except Exception as e:
            # Directory iteration failed (rare) — log but don't crash
            logger.error(f"Cleanup failed while scanning temp directory: {e}")

        return deleted

    def delete_file(self, file_path: str) -> None:
        """
        Delete a specific temp file after processing is complete.
        Silently ignores files that don't exist or can't be deleted.
        """
        try:
            path = Path(file_path)
            if path.exists() and path.is_file():
                path.unlink()
        except FileNotFoundError:
            # File already deleted — not an error
            pass
        except Exception as e:
            # Log but don't raise — cleanup is best-effort
            logger.warning(f"Failed to delete {file_path}: {e}")