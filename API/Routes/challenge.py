# ===========================================================
# SpeakSecure — Challenge Route
# POST /challenge — Generate a one-time digit challenge for a user.
# Requires X-API-Key authentication.
# ===========================================================

from fastapi import APIRouter, Form, HTTPException, Depends

from Models.schemas import ChallengeResponse, ApiKeyInfo
from Services.dependencies import challenge_service, voiceprint_repository
from API.dependencies import require_api_key

router = APIRouter(tags=["Challenge"])

@router.post("/challenge", response_model=ChallengeResponse)
async def generate_challenge(
    user_id: str = Form(...),
    api_key: ApiKeyInfo = Depends(require_api_key),
) -> ChallengeResponse:
    """
    Generate a random digit challenge that the user must speak aloud
    during verification. The challenge is single-use and expires after
    a short TTL.
    """
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

    return ChallengeResponse(success=True, **result)