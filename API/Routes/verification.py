# ===========================================================
# SpeakSecure — Verification Route
# POST /verify — Verify a user's voice against their profile.
# Requires X-API-Key authentication.
# ===========================================================

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends

from Models.schemas import VerificationResponse, ApiKeyInfo
from Services.dependencies import verification_service
from API.dependencies import require_api_key

router = APIRouter(tags=["Verification"])

@router.post("/verify", response_model=VerificationResponse)
async def verify_user(
    user_id: str = Form(...),
    audio_file: UploadFile = File(...),
    api_key: ApiKeyInfo = Depends(require_api_key),
) -> VerificationResponse:
    """
    Verify a user's identity using their voice.
    Requires an active challenge (from POST /challenge).
    Pipeline: rate limit → validate → anti-spoof → speech recognition
    → challenge match → voice comparison → decision.
    """
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

    return VerificationResponse(success=True, **result)