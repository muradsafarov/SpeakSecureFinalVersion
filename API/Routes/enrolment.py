# ===========================================================
# SpeakSecure — Enrolment Routes
#
# POST   /enrol                  - Register a NEW user with their first voice sample
# POST   /enrol/add-sample       - Add an additional sample to an existing user
# GET    /enrol/check/{user_id}  - Check if a username is already registered
# DELETE /enrol/{user_id}        - Delete a user's voice profile entirely
#
# All endpoints require X-API-Key authentication.
# ===========================================================

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends

from constants import MAX_SAMPLES_PER_USER
from Models.schemas import EnrolmentResponse, EnrolmentCheckResponse, ApiKeyInfo
from Services.dependencies import enrolment_service, voiceprint_repository
from API.dependencies import require_api_key

router = APIRouter(tags=["Enrolment"])

@router.get("/enrol/check/{user_id}", response_model=EnrolmentCheckResponse)
async def check_user(
    user_id: str,
    api_key: ApiKeyInfo = Depends(require_api_key),
) -> EnrolmentCheckResponse:
    """Check whether a username is already registered."""
    exists = voiceprint_repository.user_exists(user_id)
    num_samples = voiceprint_repository.get_sample_count(user_id) if exists else 0

    return EnrolmentCheckResponse(
        exists=exists,
        user_id=user_id,
        num_samples=num_samples,
        max_samples=MAX_SAMPLES_PER_USER,
        can_add_sample=exists and num_samples < MAX_SAMPLES_PER_USER,
    )

@router.post("/enrol", response_model=EnrolmentResponse)
async def enrol_user(
    user_id: str = Form(...),
    audio_file: UploadFile = File(...),
    api_key: ApiKeyInfo = Depends(require_api_key),
) -> EnrolmentResponse:
    """
    Register a brand new user with their first voice sample.
    Pipeline: validate → transcription check → anti-spoof → embed → store.
    Fails if the username is already taken or audio is invalid.
    """
    try:
        result = await enrolment_service.enrol_user(user_id, audio_file)
    except ValueError as e:
        detail = str(e)
        status = 409 if "already taken" in detail else 400
        raise HTTPException(status_code=status, detail=detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Enrolment failed: {e}")

    return EnrolmentResponse(success=True, **result)

@router.post("/enrol/add-sample", response_model=EnrolmentResponse)
async def add_sample(
    user_id: str = Form(...),
    audio_file: UploadFile = File(...),
    api_key: ApiKeyInfo = Depends(require_api_key),
) -> EnrolmentResponse:
    """
    Add an additional voice sample to an existing user's profile.
    Improves verification accuracy. Fails if user does not exist,
    the sample limit is reached, or the voice doesn't match.
    """
    try:
        result = await enrolment_service.add_sample(user_id, audio_file)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Adding sample failed: {e}")

    return EnrolmentResponse(success=True, **result)

@router.delete("/enrol/{user_id}")
async def delete_user(
    user_id: str,
    api_key: ApiKeyInfo = Depends(require_api_key),
):
    """
    Delete a user's voice profile and all stored samples.
    This action is irreversible — the user must re-register to use
    voice sign-in again.
    """
    if not voiceprint_repository.user_exists(user_id):
        raise HTTPException(
            status_code=404,
            detail=f"No enrolled voice profile found for user '{user_id}'.",
        )

    deleted = voiceprint_repository.delete_user(user_id)

    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete user profile.")

    return {
        "success": True,
        "user_id": user_id,
        "message": f"Voice profile for user '{user_id}' has been deleted.",
    }