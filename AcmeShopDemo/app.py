# ===========================================================
# Acme Shop Demo — FastAPI Server
#
# A minimal "third-party site" that integrates with SpeakSecure
# via the OAuth 2.0 authorization code flow.
#
# Routes:
#   GET  /                  — landing page with "Sign in" button
#   GET  /login             — generates state, redirects to SpeakSecure /authorize
#   GET  /callback          — receives ?code=...&state=... from SpeakSecure,
#                             exchanges code for user info via POST /token,
#                             creates a session cookie, redirects to /dashboard
#   GET  /dashboard         — protected page showing the signed-in user
#   GET  /logout            — clears the session
#
# Sessions are stored in-memory (dict). Survive restarts? No, but
# this is a demo — production would use Redis or a database.
# CSRF protection via the OAuth state parameter, stored in a
# short-lived cookie between /login and /callback.
# ===========================================================

import secrets
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Request, HTTPException, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import (
    SPEAKSECURE_BASE_URL,
    SPEAKSECURE_API_KEY,
    REDIRECT_URI,
    ACME_SHOP_PORT,
)

app = FastAPI(title="Acme Shop Demo")

templates = Jinja2Templates(directory="Templates")

# ===========================================================
# In-memory session store
# Maps session_id (random cookie value) → user_id (from SpeakSecure)
# In production this would be Redis or a database.
# ===========================================================
sessions: dict[str, str] = {}

# Pending OAuth state values waiting for callback.
# Maps state → True (just a set of valid in-flight states).
# In production this would also be stored server-side keyed by
# the user's session, with short TTL.
pending_states: dict[str, bool] = {}


# ===========================================================
# Helpers
# ===========================================================

def get_user_from_session(session_id: str | None) -> str | None:
    """Look up the signed-in user_id from a session cookie value, or None."""
    if not session_id:
        return None
    return sessions.get(session_id)


# ===========================================================
# Routes
# ===========================================================

@app.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    acme_session: str | None = Cookie(default=None),
):
    """
    Landing page. If the user is signed in, redirect to dashboard.
    Otherwise show the "Sign in with SpeakSecure" button.
    """
    user_id = get_user_from_session(acme_session)
    if user_id:
        return RedirectResponse(url="/dashboard", status_code=302)

    return templates.TemplateResponse("index.html", {
        "request": request,
        "shop_name": "Acme Shop",
    })


@app.get("/login")
async def login():
    """
    Initiate the OAuth flow.

    Steps:
      1. Generate a random state value (CSRF token)
      2. Remember it server-side AND set it in a short-lived cookie
      3. Redirect the browser to SpeakSecure /authorize with all
         the OAuth parameters

    The state is the OAuth 2.0 anti-CSRF mechanism: when the user
    comes back to /callback we'll verify that the state in the URL
    matches the one we issued. If not, the request is rejected.
    """
    if SPEAKSECURE_API_KEY == "PASTE_YOUR_API_KEY_HERE":
        return HTMLResponse(
            "<h1>Acme Shop is not configured</h1>"
            "<p>Set <code>SPEAKSECURE_API_KEY</code> in <code>config.py</code> "
            "or as an environment variable.</p>",
            status_code=500,
        )

    # token_urlsafe(32) gives 43 base64url characters of cryptographic
    # randomness — well beyond what's needed for CSRF protection
    state = secrets.token_urlsafe(32)
    pending_states[state] = True

    # Build the OAuth /authorize URL
    params = {
        "client_id": SPEAKSECURE_API_KEY,
        "redirect_uri": REDIRECT_URI,
        "state": state,
    }
    authorize_url = f"{SPEAKSECURE_BASE_URL}/api/v1/authorize?{urlencode(params)}"

    response = RedirectResponse(url=authorize_url, status_code=302)
    # Also set the state in a cookie — belt-and-braces protection.
    # Even if the in-memory dict is wiped (server restart), the cookie
    # check will still catch a forged state.
    response.set_cookie(
        key="acme_oauth_state",
        value=state,
        max_age=600,             # 10 minutes
        httponly=True,
        samesite="lax",
    )
    return response


@app.get("/callback", response_class=HTMLResponse)
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    acme_oauth_state: str | None = Cookie(default=None),
):
    """
    OAuth callback. Receives ?code=...&state=... from SpeakSecure.

    Steps:
      1. Validate state against what we issued (CSRF check)
      2. POST the code to SpeakSecure /token with our API key to
         get back the user_id
      3. Create a session, set cookie, redirect to /dashboard
    """
    # --- 1. State validation (CSRF protection) ---
    # Both the URL state AND the cookie state must match what we
    # remembered server-side. Any mismatch → reject.
    if not state:
        raise HTTPException(status_code=400, detail="Missing state parameter.")
    if state != acme_oauth_state:
        # Cookie didn't match — possible CSRF attempt
        raise HTTPException(status_code=400, detail="State mismatch (CSRF check failed).")
    if state not in pending_states:
        # Unknown state — possible replay or forged request
        raise HTTPException(status_code=400, detail="Unknown state.")

    # Mark state as consumed (one-time use)
    pending_states.pop(state, None)

    # --- 2. Did SpeakSecure send back an error instead of a code? ---
    if error or not code:
        return HTMLResponse(
            f"<h1>Sign-in failed</h1><p>{error or 'No code returned'}</p>"
            f"<p><a href='/'>Back to Acme Shop</a></p>",
            status_code=400,
        )

    # --- 3. Exchange code for user info (server-to-server) ---
    # This call is authenticated by our API key, which lives only on
    # the server. An attacker who tampered with the browser flow can't
    # forge this request because they don't have the API key.
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_response = await client.post(
                f"{SPEAKSECURE_BASE_URL}/api/v1/token",
                headers={
                    "X-API-Key": SPEAKSECURE_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "code": code,
                    "redirect_uri": REDIRECT_URI,
                },
            )
    except httpx.RequestError as e:
        return HTMLResponse(
            f"<h1>Could not reach SpeakSecure</h1><p>{e}</p>"
            f"<p><a href='/'>Back to Acme Shop</a></p>",
            status_code=502,
        )

    if token_response.status_code != 200:
        return HTMLResponse(
            f"<h1>Token exchange failed</h1>"
            f"<p>SpeakSecure returned {token_response.status_code}: {token_response.text}</p>"
            f"<p><a href='/'>Back to Acme Shop</a></p>",
            status_code=502,
        )

    token_data = token_response.json()

    if not token_data.get("valid") or not token_data.get("user_id"):
        # Code was rejected (expired, already used, wrong key, etc.)
        return HTMLResponse(
            f"<h1>Sign-in failed</h1>"
            f"<p>SpeakSecure rejected the authorization code: "
            f"{token_data.get('reason', 'unknown')}</p>"
            f"<p><a href='/'>Back to Acme Shop</a></p>",
            status_code=400,
        )

    user_id = token_data["user_id"]

    # --- 4. Create session, redirect to dashboard ---
    session_id = secrets.token_urlsafe(32)
    sessions[session_id] = user_id

    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key="acme_session",
        value=session_id,
        max_age=3600 * 24,       # 24 hours
        httponly=True,
        samesite="lax",
    )
    # Clear the OAuth state cookie now that the flow is complete
    response.delete_cookie(key="acme_oauth_state")
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    acme_session: str | None = Cookie(default=None),
):
    """Protected page — only accessible after successful sign-in."""
    user_id = get_user_from_session(acme_session)
    if not user_id:
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "shop_name": "Acme Shop",
        "user_id": user_id,
    })


@app.get("/logout")
async def logout(acme_session: str | None = Cookie(default=None)):
    """Clear the session and redirect home."""
    if acme_session:
        sessions.pop(acme_session, None)

    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie(key="acme_session")
    return response


# ===========================================================
# Static files for CSS
# ===========================================================
app.mount(
    "/static",
    StaticFiles(directory="Templates"),
    name="static",
)


# ===========================================================
# Entry point
# ===========================================================
if __name__ == "__main__":
    import uvicorn
    print(f"Acme Shop running on http://localhost:{ACME_SHOP_PORT}")
    print(f"SpeakSecure backend expected at: {SPEAKSECURE_BASE_URL}")
    print(f"Redirect URI: {REDIRECT_URI}")
    uvicorn.run(app, host="0.0.0.0", port=ACME_SHOP_PORT)