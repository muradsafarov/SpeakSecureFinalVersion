# ===========================================================
# SpeakSecure — API Key Generation & Hashing
#
# SECURITY MODEL:
#   1. A new API key is generated with a cryptographically secure random
#      value (secrets.token_hex). It's shown to the integrator ONCE.
#   2. Only the SHA-256 hash is stored in the database. The plaintext
#      key cannot be recovered from the hash, so if the database leaks
#      the attacker cannot use the keys.
#   3. On every API request, the incoming key is hashed and compared
#      against the stored hash. No plaintext comparison ever happens.
#
# This is the same pattern used by Stripe, GitHub, and AWS.
#
# KEY FORMAT: ss_live_<32 hex chars> for production integrations,
#             ss_test_<32 hex chars> for testing/demo integrations.
# ===========================================================

import hashlib
import re
import secrets

# Prefix indicates the key environment (live vs test).
# Prefixes are visible in logs and dashboards, making it obvious
# which environment a key belongs to.
LIVE_PREFIX = "ss_live_"
TEST_PREFIX = "ss_test_"

# Length of the random portion (in hex chars).
# 32 hex chars = 128 bits of entropy, well beyond what's needed
# to prevent brute force. Stripe uses ~28 chars, we use 32.
KEY_RANDOM_LENGTH = 32

# Length of the prefix shown in UI/logs to identify a key without
# exposing it. E.g. full key "ss_live_a3f2b1c4..." → display "ss_live_a3f2"
KEY_DISPLAY_PREFIX_LENGTH = 12

# Regex used to validate the structure of an incoming key before any
# database lookup. Cheaper than hashing + DB read for malformed input.
_KEY_FORMAT_RE = re.compile(r"^ss_(live|test)_[a-f0-9]{32}$")


def generate_api_key(environment: str = "live") -> str:
    """
    Generate a new cryptographically secure API key.

    Args:
        environment: "live" for production keys, "test" for demo/test keys.

    Returns:
        The plaintext API key. This is the ONLY time this value exists —
        the caller must immediately display it to the integrator and
        store only its hash.
    """
    if environment not in ("live", "test"):
        raise ValueError(f"Invalid environment '{environment}'. Use 'live' or 'test'.")

    prefix = LIVE_PREFIX if environment == "live" else TEST_PREFIX
    # secrets.token_hex is cryptographically secure — suitable for tokens,
    # API keys, password resets, etc. Uses the OS entropy pool.
    random_part = secrets.token_hex(KEY_RANDOM_LENGTH // 2)  # 16 bytes → 32 hex chars
    return prefix + random_part


def hash_api_key(plaintext_key: str) -> str:
    """
    Compute the SHA-256 hash of an API key.
    This is what's stored in the database — never the plaintext key.

    SHA-256 is appropriate here (not bcrypt/argon2) because API keys
    have high entropy (128 bits of randomness). Slow hashing algorithms
    like bcrypt are needed for low-entropy passwords; for random tokens
    a fast hash is sufficient and faster to verify on every request.
    """
    return hashlib.sha256(plaintext_key.encode("utf-8")).hexdigest()


def get_display_prefix(plaintext_key: str) -> str:
    """
    Extract the first few characters of a key for safe display.
    E.g. "ss_live_a3f2b1c4d5e6..." → "ss_live_a3f2"
    Used in CLI output, admin UIs, logs — places where you need to
    identify a key without exposing it fully.
    """
    return plaintext_key[:KEY_DISPLAY_PREFIX_LENGTH]


def is_valid_key_format(plaintext_key: str) -> bool:
    """
    Sanity-check the structure of an incoming API key.
    Returns True if the key matches the expected `ss_(live|test)_<32hex>`
    pattern, False otherwise. Catches obvious malformed input cheaply
    before hitting the database.
    """
    if not plaintext_key:
        return False
    return bool(_KEY_FORMAT_RE.match(plaintext_key))