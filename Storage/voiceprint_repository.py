# ===========================================================
# SpeakSecure — Voiceprint Repository
# Stores and manages voice embeddings locally on disk.
# Each user gets a directory with their samples and profile.
# Privacy-first: all data stays on the local device.
#
# Storage structure:
#   Data/Embeddings/{user_id}/
#     ├── embeddings.pt   — list of all individual voice samples
#     └── profile.pt      — averaged (mean) voice profile for comparison
# ===========================================================

import re
import shutil
from pathlib import Path

import torch

from config import EMBEDDINGS_DIR

# Expected embedding dimension from ECAPA-TDNN
EXPECTED_EMBEDDING_DIM = 192

# Only these characters are allowed in a sanitized user_id.
# Everything else is stripped. This prevents path traversal
# (e.g. "../../etc/passwd") and other filesystem tricks.
_UNSAFE_USER_ID_CHARS = re.compile(r"[^a-z0-9_\-]")


class VoiceprintRepository:
    """Local storage for voice embeddings. No data leaves the device."""

    def __init__(self):
        self.embeddings_dir = EMBEDDINGS_DIR
        self.embeddings_dir.mkdir(parents=True, exist_ok=True)

    # ==================== Path helpers ====================

    def _sanitize(self, user_id: str) -> str:
        """
        Normalize user_id into a filesystem-safe directory name.

        Strips leading/trailing whitespace, lowercases, replaces spaces
        with underscores, and removes any character that isn't a–z, 0–9,
        underscore or hyphen. This prevents path traversal attacks
        (e.g. a user_id like "../../etc/passwd" cannot escape the
        embeddings directory) and keeps directory names portable
        across filesystems.
        """
        safe = user_id.strip().replace(" ", "_").lower()
        safe = _UNSAFE_USER_ID_CHARS.sub("", safe)
        if not safe:
            raise ValueError(
                "Invalid user_id: must contain at least one letter or digit "
                "(allowed characters: a-z, 0-9, underscore, hyphen)."
            )
        return safe

    def _user_dir(self, user_id: str) -> Path:
        """
        Return the path to a user's directory WITHOUT creating it.
        Used by read operations (user_exists, get_sample_count, delete_user)
        so that checking for a non-existent user does not create an empty
        folder on disk.
        """
        return self.embeddings_dir / self._sanitize(user_id)

    def _ensure_user_dir(self, user_id: str) -> Path:
        """
        Return the path to a user's directory and create it if missing.
        Used only by write operations (add_embedding).
        """
        user_dir = self._user_dir(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    def _samples_path(self, user_id: str) -> Path:
        """Path to the file storing all individual enrolment samples."""
        return self._user_dir(user_id) / "embeddings.pt"

    def _profile_path(self, user_id: str) -> Path:
        """Path to the averaged voice profile used for verification."""
        return self._user_dir(user_id) / "profile.pt"

    # ==================== Validation ====================

    def _validate_embedding(self, embedding, user_id: str) -> None:
        """
        Validate that a loaded embedding is a proper 192-dim tensor.
        Raises ValueError if the embedding is corrupted or malformed.
        """
        if not isinstance(embedding, torch.Tensor):
            raise ValueError(
                f"Voice profile for user '{user_id}' is corrupted: "
                f"expected torch.Tensor, got {type(embedding).__name__}"
            )

        if embedding.dim() != 1 or embedding.shape[0] != EXPECTED_EMBEDDING_DIM:
            raise ValueError(
                f"Voice profile for user '{user_id}' has wrong shape: "
                f"expected ({EXPECTED_EMBEDDING_DIM},), got {tuple(embedding.shape)}"
            )

        if torch.isnan(embedding).any() or torch.isinf(embedding).any():
            raise ValueError(
                f"Voice profile for user '{user_id}' contains invalid values (NaN or Inf)"
            )

    # ==================== Public API ====================

    def add_embedding(self, user_id: str, embedding: torch.Tensor) -> dict:
        """
        Add a new voice sample and recompute the averaged profile.
        Creates the user directory if this is the first sample.
        Multiple samples improve accuracy by averaging out variations.
        """
        self._validate_embedding(embedding, user_id)

        # This is a write operation — it's correct to create the directory here
        user_dir = self._ensure_user_dir(user_id)
        samples_path = user_dir / "embeddings.pt"
        profile_path = user_dir / "profile.pt"

        # Load existing samples or start a new list
        if samples_path.exists():
            try:
                embeddings = torch.load(samples_path, weights_only=True)
            except Exception as e:
                raise ValueError(
                    f"Failed to load existing samples for user '{user_id}': {e}"
                )
            if not isinstance(embeddings, list):
                embeddings = [embeddings]
        else:
            embeddings = []

        # Append new sample and save all samples
        embeddings.append(embedding.detach().cpu())
        torch.save(embeddings, samples_path)

        # Recompute averaged profile from all samples
        stacked = torch.stack(embeddings)
        averaged = torch.mean(stacked, dim=0)
        averaged = torch.nn.functional.normalize(averaged, p=2, dim=0)
        torch.save(averaged, profile_path)

        return {
            "num_samples": len(embeddings),
            "samples_path": str(samples_path),
            "profile_path": str(profile_path),
        }

    def load_profile(self, user_id: str) -> torch.Tensor:
        """
        Load the averaged voice profile for comparison during verification.
        Validates that the loaded tensor has the expected shape and values.
        """
        profile_path = self._profile_path(user_id)

        if not profile_path.exists():
            raise FileNotFoundError(
                f"No voice profile found for user '{user_id}'."
            )

        try:
            profile = torch.load(profile_path, weights_only=True)
        except Exception as e:
            raise ValueError(
                f"Failed to load voice profile for user '{user_id}': {e}"
            )

        self._validate_embedding(profile, user_id)

        return profile

    def user_exists(self, user_id: str) -> bool:
        """
        Check if a user has an enrolled voice profile on disk.
        Read-only: does not create any directories for non-existent users.
        """
        return self._profile_path(user_id).exists()

    def get_sample_count(self, user_id: str) -> int:
        """
        Get the number of enrolment samples stored for a user.
        Read-only: does not create any directories for non-existent users.
        """
        samples_path = self._samples_path(user_id)

        if not samples_path.exists():
            return 0

        try:
            samples = torch.load(samples_path, weights_only=True)
        except Exception:
            return 0

        return len(samples) if isinstance(samples, list) else 0

    def delete_user(self, user_id: str) -> bool:
        """
        Delete all stored voice data for a user.
        Removes the user directory and all its contents.
        Returns True only if the directory was actually removed.
        Uses shutil.rmtree with ignore_errors=True so permission
        problems don't raise — the return value indicates real success.
        """
        user_dir = self._user_dir(user_id)

        if not user_dir.exists():
            return False

        shutil.rmtree(user_dir, ignore_errors=True)
        # Return True only if the directory is actually gone
        return not user_dir.exists()