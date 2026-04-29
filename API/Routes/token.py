# ===========================================================
# SpeakSecure — OAuth Token Endpoint
#
# POST /token — Server-to-server authorization code exchange.
#
# This is the OAuth 2.0 token endpoint, RFC 6749 §3.2.
#
#   1. User completes voice verification on /authorize → we issue a code
#   2. Browser is redirected to integrator's /callback?code=...&state=...
#   3. Integrator's BACKEND (not browser!) calls THIS endpoint:
#         POST /token
#         X-API-Key: ss_live_...
#         { "code": "...", "redirect_uri": "..." }
#   4. We return verified user identity, code is consumed.
#
# Why server-to-server? The X-API-Key authenticating this call lives
# ONLY on the integrator's backend — never in their JavaScript. An
# attacker who tampers with the frontend can't forge this request,
# because they don't have the API key.
# ===========================================================

from fastapi import APIRouter, Depends, HTTPException

from Models.schemas import TokenRequest, TokenResponse, ApiKeyInfo
from Services.dependencies import oauth_service
from API.dependencies import require_api_key

router = APIRouter(tags=["OAuth Token"])


@router.post("/token", response_model=TokenResponse)
async def exchange_token(
    body: TokenRequest,
    api_key: ApiKeyInfo = Depends(require_api_key),
) -> TokenResponse:
    """
    Exchange an authorization code for the verification result.

    Called by the integrator's BACKEND, not by a browser. The API key
    authenticating this request MUST be the same one that initiated
    the original /authorize flow — otherwise the exchange fails.
    The redirect_uri MUST match the one used during /authorize too.

    Codes are single-use. Once exchanged, subsequent attempts fail
    with a generic "invalid_or_expired" reason.

    Returns a TokenResponse:
        valid=true → user_id, verified, decision, similarity_score
        valid=false → reason field (deliberately generic for security)
    """
    if not body.code or not body.code.strip():
        raise HTTPException(status_code=400, detail="Missing code in request body.")

    if not body.redirect_uri or not body.redirect_uri.strip():
        raise HTTPException(status_code=400, detail="Missing redirect_uri in request body.")

    result = oauth_service.exchange_code(
        code=body.code.strip(),
        api_key_id=api_key.id,
        redirect_uri=body.redirect_uri.strip(),
    )

    if result is None:
        # Single generic error — does not reveal whether the code was
        # unknown, expired, already used, belonged to a different
        # API key, or used a different redirect_uri. All four cases
        # are indistinguishable from the attacker's perspective.
        return TokenResponse(
            valid=False,
            reason="invalid_or_expired",
        )

    return TokenResponse(
        valid=True,
        user_id=result["user_id"],
        verified=result["verified"],
        decision=result["decision"],
        similarity_score=result["similarity_score"],
    )