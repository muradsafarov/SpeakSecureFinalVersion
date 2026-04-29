# ===========================================================
# SpeakSecure — API Router
# Collects all route modules into a single router.
# This is the central hub that registers all API endpoints.
# Mounted in main.py under the /api/v1 prefix.
#
# The API has TWO surfaces:
#   1. Public API — direct voice ops, protected by X-API-Key.
#      Used by SpeakSecure's own demo (and by any integrator that
#      wants to call us directly without the OAuth flow).
#   2. OAuth flow — third-party integrations following RFC 6749.
#      The integrator redirects users to /authorize; we handle the
#      voice verification and redirect back with a code; the
#      integrator's backend exchanges the code via /token.
# ===========================================================

from fastapi import APIRouter

from API.Routes.health import router as health_router
from API.Routes.status import router as status_router
from API.Routes.enrolment import router as enrolment_router
from API.Routes.challenge import router as challenge_router
from API.Routes.verification import router as verification_router
from API.Routes.authorize import router as authorize_router
from API.Routes.token import router as token_router

# Main router that aggregates all sub-routers
api_router = APIRouter()

# --- Public, no API key required ---
api_router.include_router(health_router)        # GET  /health
api_router.include_router(status_router)        # GET  /status

# --- Public API, X-API-Key required ---
api_router.include_router(enrolment_router)     # POST /enrol, POST /enrol/add-sample,
                                                # GET /enrol/check/{user_id},
                                                # DELETE /enrol/{user_id}
api_router.include_router(challenge_router)     # POST /challenge
api_router.include_router(verification_router)  # POST /verify

# --- OAuth flow for third-party integrations ---
api_router.include_router(authorize_router)     # GET /authorize, POST /authorize/*
api_router.include_router(token_router)         # POST /token (server-to-server)