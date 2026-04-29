# ===========================================================
# SpeakSecure — API Dependencies
# FastAPI dependencies used across routes.
#
# The main export is require_api_key() — a dependency that:
#   1. Extracts X-API-Key header from the request
#   2. Hashes it and looks up in the database
#   3. Validates that the requesting origin is allowed for this key
#   4. Atomically increments the per-key request counter and checks
#      the hourly rate limit
#   5. Rejects the request with 401 / 429 if anything is wrong
#   6. Returns an ApiKeyInfo object for use in the route handler
#
# Usage in a route:
#   @router.post("/protected")
#   async def protected(api_key: ApiKeyInfo = Depends(require_api_key)):
#       # api_key.id, api_key.name etc. are now available
# ===========================================================

from fastapi import Header, HTTPException, Request, status
from loguru import logger

from Models.schemas import ApiKeyInfo
from Security.api_keys import hash_api_key, is_valid_key_format
from Services.dependencies import api_key_repository, api_key_rate_limiter

async def require_api_key(
    request: Request,
    x_api_key: str = Header(
        None,
        alias="X-API-Key",
        description="API key for authentication",
    ),
) -> ApiKeyInfo:
    """
    FastAPI dependency that validates the X-API-Key header, the request
    origin, and the per-key hourly rate limit.

    Steps (in order of cheapest to most expensive):
      1. Check header is present        → 401 if missing
      2. Sanity-check key format        → 401 if malformed
      3. Database lookup by hash        → 401 if unknown / revoked
      4. Origin check (if registered)   → 401 if disallowed
      5. Rate limit check (atomic)      → 429 if exceeded

    Each step's error is deliberately generic so an attacker cannot
    distinguish between "key doesn't exist" and "key is revoked" etc.

    Returns:
        ApiKeyInfo with id, name, origins, and rate_limit fields.
        Route handlers can use this to log usage or enforce per-key
        rules downstream.

    Raises:
        HTTPException(401) if the key is missing, malformed, unknown,
            revoked, or the request origin is not allowed.
        HTTPException(429) if the key's hourly quota is exhausted.
    """

    # --- 1. Header must be present ---
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header.",
        )

    # --- 2. Quick format check (cheap, avoids a DB lookup for garbage) ---
    if not is_valid_key_format(x_api_key):
        logger.warning("Rejected malformed API key attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )

    # --- 3. Hash + database lookup ---
    key_hash = hash_api_key(x_api_key)
    key_record = api_key_repository.find_by_hash(key_hash)

    if key_record is None:
        # Either unknown OR revoked — deliberately vague to not leak info.
        # find_by_hash filters revoked keys out at the SQL level.
        logger.warning("Rejected unknown or revoked API key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )

    # --- 4. Origin check ---
    # If the key has registered origins, the request Origin header must
    # match one of them. Empty origins list means "any origin" which is
    # meant for server-to-server keys where no browser is involved.
    allowed_origins = key_record["origins"]
    if allowed_origins:
        request_origin = request.headers.get("origin")
        if request_origin and request_origin not in allowed_origins:
            logger.warning(
                f"API key '{key_record['name']}' (id={key_record['id']}) "
                f"used from disallowed origin: {request_origin}"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="This origin is not allowed to use this API key.",
            )

    # --- 5. Per-key rate limit (atomic increment + check) ---
    # Done LAST so that invalid keys don't pollute the usage counter.
    # The increment is atomic (SQLite upsert) so concurrent requests
    # can't both sneak past the last slot.
    allowed, current_count, limit = api_key_rate_limiter.check_and_increment(
        api_key_id=key_record["id"],
        limit_per_hour=key_record["rate_limit_per_hour"],
    )

    if not allowed:
        logger.warning(
            f"Rate limit exceeded for API key '{key_record['name']}' "
            f"(id={key_record['id']}): {current_count}/{limit} this hour"
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"API key rate limit exceeded: {limit} requests per hour. "
                f"Try again at the top of the next hour."
            ),
            headers={
                # Standard rate-limit headers help integrators handle this gracefully
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
                "Retry-After": "3600",  # seconds until next bucket
            },
        )

    logger.debug(
        f"Authenticated request with API key '{key_record['name']}' "
        f"(id={key_record['id']}, usage {current_count}/{limit})"
    )

    return ApiKeyInfo(
        id=key_record["id"],
        name=key_record["name"],
        key_prefix=key_record["key_prefix"],
        origins=key_record["origins"],
        rate_limit_per_hour=key_record["rate_limit_per_hour"],
    )