# ===========================================================
# SpeakSecure — OAuth 2.0 Authorize Routes
#
# The OAuth 2.0 authorization code flow on our side:
#
#   GET  /authorize?client_id=...&redirect_uri=...&state=...
#        → Validates parameters and serves the HTML page where
#          the user enters their voice. The validated parameters
#          are embedded in the page so the page's JS can pass
#          them back to /authorize/submit-signin.
#
#   POST /authorize/challenge
#        → Internal: generate a digit challenge the user must speak.
#          Authenticated by client_id+state combo, not by an X-API-Key
#          header — this endpoint is only meant to be called from our
#          own /authorize page.
#
#   POST /authorize/submit-signin
#        → Internal: receive audio, run verification, and on success
#          generate an authorization code, then return the redirect
#          URL to the page.
#
# The /authorize page itself lives in OAuthFrontend/authorize.html
# and is served from disk by GET /authorize. The frontend is a
# separate single-purpose application — see main.py for the static
# mount setup.
#
# NOTE on client_id:
#   In OAuth 2.0 terminology client_id identifies the integrator. We
#   use the API key as the client_id, sent in the URL (visible to the
#   end user). The key alone doesn't grant access — it must match a
#   registered redirect_uri AND the integrator's backend must use it
#   again as X-API-Key when exchanging the authorization code via
#   POST /token. This is the same pattern Stripe and Auth0 use for
#   their OAuth flows.
# ===========================================================

from html import escape
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse
from loguru import logger

from Models.schemas import (
    AuthorizeChallengeResponse,
    AuthorizeSubmitResponse,
    ClientInfoResponse,
)
from Security.api_keys import hash_api_key, is_valid_key_format
from Services.dependencies import (
    api_key_repository,
    challenge_service,
    verification_service,
    oauth_service,
    voiceprint_repository,
)

router = APIRouter(tags=["OAuth Authorize"])


# Path to the HTML template — lives in OAuthFrontend/, separate from
# the main self-service Demo/ app.
OAUTH_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "OAuthFrontend" / "authorize.html"
)


# ==================== Helpers ====================

def _validate_client(client_id: str, redirect_uri: str, state: str) -> dict:
    """
    Validate the three parameters that come in to every /authorize call.
    Returns the API key record on success, raises HTTPException on failure.

    Checks (in this order):
      1. client_id must look like a valid API key (regex check)
      2. redirect_uri must be present
      3. state must be present (REQUIRED — CSRF protection)
      4. client_id must resolve to a non-revoked API key in the DB
      5. redirect_uri must be in the registered whitelist for this key

    The redirect_uri whitelist check (step 5) is critical: without it,
    an attacker could craft a phishing /authorize URL with their own
    redirect_uri and steal the user's authorization code.
    """
    if not client_id or not is_valid_key_format(client_id):
        raise HTTPException(status_code=400, detail="Invalid client_id.")

    if not redirect_uri:
        raise HTTPException(status_code=400, detail="Missing redirect_uri.")

    # state is REQUIRED in our implementation (CSRF protection).
    # OAuth 2.0 makes it optional but heavily recommended; we choose
    # to enforce it because every modern client should send one.
    if not state:
        raise HTTPException(status_code=400, detail="Missing state parameter.")

    key_hash = hash_api_key(client_id)
    key_record = api_key_repository.find_by_hash(key_hash)
    if key_record is None:
        # Same generic 400 — don't reveal whether the key exists.
        # We use 400 here (not 401) because this is a parameter error
        # surfaced to a browser, not an authenticated API call.
        raise HTTPException(status_code=400, detail="Invalid client_id.")

    if not api_key_repository.is_redirect_uri_allowed(key_record["id"], redirect_uri):
        # CRITICAL security check — without this, an attacker can phish
        # users to evil.com by crafting a malicious /authorize URL.
        logger.warning(
            f"Rejected /authorize: client '{key_record['name']}' "
            f"(id={key_record['id']}) used unregistered redirect_uri: {redirect_uri}"
        )
        raise HTTPException(
            status_code=400,
            detail="redirect_uri is not registered for this client_id.",
        )

    return key_record


def _build_redirect(redirect_uri: str, params: dict) -> str:
    """
    Build the final redirect URL with query parameters appended.
    Preserves any existing query string on redirect_uri (rare but legal).
    """
    sep = "&" if "?" in redirect_uri else "?"
    return redirect_uri + sep + urlencode(params)


# ==================== GET /authorize — HTML entry point ====================

@router.get("/authorize", response_class=HTMLResponse)
async def authorize_page(
    client_id: str = "",
    redirect_uri: str = "",
    state: str = "",
):
    """
    The OAuth entry point. Validates client_id / redirect_uri / state and
    serves the HTML page where the user signs in with their voice.

    On any validation error we don't redirect (we don't trust the
    redirect_uri yet) — we render an error page so the user knows what
    happened. This matches the recommendation in RFC 6749 §4.1.2.1.
    """
    try:
        key_record = _validate_client(client_id, redirect_uri, state)
    except HTTPException as e:
        # Render a simple error page instead of redirecting — we don't
        # trust the redirect_uri until we've validated it.
        return HTMLResponse(
            f"""
            <!DOCTYPE html>
            <html><head><title>SpeakSecure — Authorization Error</title>
            <style>
                body {{ font-family: sans-serif; max-width: 500px;
                        margin: 80px auto; padding: 20px;
                        background: #0a0b0f; color: #e6e8ee; }}
                h1 {{ color: #f87171; }}
            </style></head>
            <body>
                <h1>Authorization Error</h1>
                <p>{escape(e.detail)}</p>
                <p>If you arrived here from a third-party site, please
                contact that site's administrator.</p>
            </body></html>
            """,
            status_code=e.status_code,
        )

    # Read the authorize.html template from disk and inject parameters.
    # We embed client_id, redirect_uri and state into the page so the
    # page's JS can echo them back when calling /authorize/submit-*.
    if not OAUTH_TEMPLATE_PATH.exists():
        return HTMLResponse(
            "<h1>SpeakSecure /authorize page not found</h1>"
            "<p>OAuthFrontend/authorize.html is missing.</p>",
            status_code=500,
        )

    html = OAUTH_TEMPLATE_PATH.read_text(encoding="utf-8")

    # Simple template substitution — the HTML uses {{client_id}} placeholders.
    # Values are escaped because they're embedded in HTML attributes;
    # they've already passed regex / DB validation but defence-in-depth
    # never hurts.
    html = html.replace("{{client_id}}", escape(client_id, quote=True))
    html = html.replace("{{redirect_uri}}", escape(redirect_uri, quote=True))
    html = html.replace("{{state}}", escape(state, quote=True))
    html = html.replace("{{integrator_name}}", escape(key_record["name"], quote=True))

    return HTMLResponse(html)


# ==================== POST /authorize/challenge ====================

@router.post("/authorize/challenge", response_model=AuthorizeChallengeResponse)
async def authorize_challenge(
    user_id: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    state: str = Form(...),
):
    """
    Generate a digit challenge for the user to speak.
    Internal endpoint — used only by our /authorize page. We re-validate
    client_id/redirect_uri/state on every call so an attacker can't
    invoke /authorize/challenge without going through GET /authorize first.
    """
    _validate_client(client_id, redirect_uri, state)

    if not voiceprint_repository.user_exists(user_id):
        raise HTTPException(
            status_code=404,
            detail=f"No enrolled voice profile found for user '{user_id}'.",
        )

    try:
        result = await challenge_service.generate_challenge(user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Challenge generation failed: {e}")

    return AuthorizeChallengeResponse(
        success=True,
        challenge=result["challenge"],
        expires_in_seconds=result["expires_in_seconds"],
    )


# ==================== POST /authorize/submit-signin ====================

@router.post("/authorize/submit-signin", response_model=AuthorizeSubmitResponse)
async def authorize_submit_signin(
    user_id: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    state: str = Form(...),
    audio_file: UploadFile = File(...),
):
    """
    The core sign-in step in the OAuth flow.

    Pipeline:
      1. Re-validate client_id / redirect_uri / state
      2. Run verification_service.verify_user — same logic as the public
         POST /verify endpoint: spoof check, challenge match, voice match
      3. If verified, generate an authorization code bound to this
         (api_key_id, redirect_uri) pair
      4. Return the result + a redirect_url to navigate to. The page's
         JS then does a window.location.href = redirect_url.

    On failure (wrong code, spoof, voice mismatch) we DO NOT generate
    a code — the page stays on /authorize and lets the user retry.
    """
    key_record = _validate_client(client_id, redirect_uri, state)

    try:
        result = await verification_service.verify_user(user_id, audio_file)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        detail = str(e)
        status = 429 if "locked" in detail.lower() or "rate limit" in detail.lower() else 400
        raise HTTPException(status_code=status, detail=detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Verification failed: {e}")

    redirect_url = None

    if result.get("verified"):
        # Generate the authorization code and build the redirect URL.
        # The integrator's backend will exchange this code via POST /token.
        code_info = oauth_service.create_authorization_code(
            user_id=result["user_id"],
            verified=True,
            api_key_id=key_record["id"],
            redirect_uri=redirect_uri,
            similarity_score=result.get("similarity_score"),
            decision=result.get("decision", "accepted"),
        )
        redirect_url = _build_redirect(redirect_uri, {
            "code": code_info["code"],
            "state": state,
        })

    # Whether verified or not, return the full result so the page can
    # show appropriate feedback. On success it also navigates.
    return AuthorizeSubmitResponse(
        success=True,
        redirect_url=redirect_url,
        **result,
    )


# ==================== GET /oauth/client-info ====================

@router.get("/oauth/client-info", response_model=ClientInfoResponse)
async def get_client_info(client_id: str):
    """
    Public endpoint — returns the human-readable name for a given
    OAuth client_id (API key). The Demo standalone calls this to
    populate banners like 'You are creating an account to sign in
    to <name>' during the register-redirect flow.

    Security considerations:
    - The endpoint is PUBLIC (no API key required) because the
      client_id itself is already public — it's visible in the
      OAuth /authorize URL. Returning the name reveals nothing
      that an attacker couldn't already see.
    - We ONLY return a name for keys that have at least one
      registered redirect_uri (i.e. real OAuth integrators, not
      self-service keys). This prevents the endpoint from being
      used to enumerate self-service keys.
    - We use the same generic error for 'not found' and 'not an
      OAuth integrator' so the response doesn't distinguish between
      an invalid key and a self-service key.
    - The format-validation step rejects malformed strings up front
      before any database lookup, so this endpoint can't be used as
      a timing oracle to probe the keys table.
    """
    # 1. Format check first — reject obvious garbage before hitting DB
    if not is_valid_key_format(client_id):
        raise HTTPException(status_code=404, detail="Unknown client")

    # 2. Hash and look up. find_by_hash already filters out revoked keys
    #    (revoked_at IS NULL check in the SQL), so a returned record is
    #    automatically active — no extra is_active check needed.
    key_hash = hash_api_key(client_id)
    key_record = api_key_repository.find_by_hash(key_hash)
    if not key_record:
        raise HTTPException(status_code=404, detail="Unknown client")

    # 3. Only OAuth integrators have redirect_uris — refuse to leak
    #    the name of self-service keys (they're not meant to be shown
    #    in any user-facing context).
    if not key_record.get("redirect_uris"):
        raise HTTPException(status_code=404, detail="Unknown client")

    return ClientInfoResponse(name=key_record["name"])