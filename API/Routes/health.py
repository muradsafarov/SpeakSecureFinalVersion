# ===========================================================
# SpeakSecure — Health Route
# Simple health check to confirm the API is running.
# ===========================================================

from fastapi import APIRouter

router = APIRouter(tags=["Health"])

@router.get("/health")
def health_check():
    """
    Basic health check endpoint.
    Returns OK status if the API is running and reachable.
    Used by monitoring tools and frontend connectivity checks.
    """
    return {
        "status": "ok",
        "service": "SpeakSecure API",
    }