# ===========================================================
# Acme Shop Demo - FastAPI Server
#
# A minimal "third-party site" that integrates with SpeakSecure
# via the OAuth 2.0 authorization code flow.
#
# Routes:
#   GET  /                  - landing page with "Sign in" button
#                              (button opens SpeakSecure in a new tab)
#   GET  /callback          - receives ?code=...&state=... from SpeakSecure,
#                              exchanges code for user info via POST /token,
#                              creates a session cookie, redirects to /dashboard
#   GET  /dashboard         - protected page showing the signed-in user
#   GET  /logout            - clears the session
#
# Sessions are stored in-memory (dict). They survive only as long
# as the server is running, but this is a demo - production would
# use Redis or a database.
#
# CSRF protection via the OAuth state parameter, stored server-side
# in pending_states. When the deployment runs inside a third-party
# iframe (Hugging Face Spaces dashboard wrapper), the cookie-based
# state check would fail because the new tab opened by the sign-in
# button is a different browsing context. We therefore validate
# the state purely against the in-memory dict, which is sufficient
# for CSRF protection in this demo.
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
# Maps session_id (random cookie value) -> user_id (from SpeakSecure)
# In production this would be Redis or a database.
# ===========================================================
sessions: dict[str, str] = {}

# Pending OAuth state values waiting for callback.
# Maps state -> True (just a set of valid in-flight states).
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


def build_authorize_url() -> str:
    """
    Generate a fresh authorize URL with a server-side state token.

    Called from the home route so the rendered HTML can use a plain
    <a target="_blank"> button - this is required to escape the
    Hugging Face Spaces iframe sandbox, which blocks both
    window.top.location and target="_top" but still allows new-tab
    navigation.
    """
    state = secrets.token_urlsafe(32)
    pending_states[state] = True

    params = {
        "client_id": SPEAKSECURE_API_KEY,
        "redirect_uri": REDIRECT_URI,
        "state": state,
    }
    return f"{SPEAKSECURE_BASE_URL}/api/v1/authorize?{urlencode(params)}"


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

    The button on the rendered page is an <a target="_blank"> that
    points directly at the authorize URL we generate here, so the
    OAuth flow opens in a top-level browsing context with full
    microphone access (which is what voice biometrics requires).
    """
    user_id = get_user_from_session(acme_session)
    if user_id:
        return RedirectResponse(url="/dashboard", status_code=302)

    if SPEAKSECURE_API_KEY == "PASTE_YOUR_API_KEY_HERE":
        # Show a clear error in development if the key was never set
        authorize_url = "/login-not-configured"
    else:
        authorize_url = build_authorize_url()

    return templates.TemplateResponse("index.html", {
        "request": request,
        "shop_name": "Acme Shop",
        "authorize_url": authorize_url,
    })


@app.get("/login-not-configured", response_class=HTMLResponse)
async def login_not_configured():
    """Friendly error page if the operator forgot to set the API key."""
    return HTMLResponse(
        "<h1>Acme Shop is not configured</h1>"
        "<p>Set <code>SPEAKSECURE_API_KEY</code> as an environment variable "
        "(or in <code>config.py</code> for local development).</p>",
        status_code=500,
    )


@app.get("/callback", response_class=HTMLResponse)
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    """
    OAuth callback. Receives ?code=...&state=... from SpeakSecure.

    Steps:
      1. Validate state against the server-side pending_states dict
         (CSRF check). The state is stored only in memory because
         the cookie approach would fail when the sign-in tab is a
         different browsing context from the original Acme Shop tab.
      2. POST the code to SpeakSecure /token with our API key to
         get back the user_id.
      3. Create a session, set cookie, redirect to /dashboard.
    """
    # --- 1. State validation (CSRF protection) ---
    if not state:
        raise HTTPException(status_code=400, detail="Missing state parameter.")
    if state not in pending_states:
        # Unknown or already-consumed state - possible replay or forgery
        raise HTTPException(status_code=400, detail="Unknown or expired state.")

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
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    acme_session: str | None = Cookie(default=None),
):
    """Protected page - only accessible after successful sign-in."""
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