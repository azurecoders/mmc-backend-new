import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_db,
    require_permissions,
)
from app.crud.crud_patient import crud_patient
from app.models.user import User
from app.schemas.patient import (
    PatientMedicalProfileResponse,
    PatientMedicalProfileUpdate,
)

router = APIRouter()

@router.get(
    "/me/medical-profile",
    response_model=PatientMedicalProfileResponse,
    summary="Patient views their own detailed medical profile and health history",
)
async def get_my_medical_profile(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    profile = await crud_patient.get_or_create_profile(db, current_user.id)
    return profile

@router.put(
    "/me/medical-profile",
    response_model=PatientMedicalProfileResponse,
    summary="Patient updates their detailed medical history archive",
)
async def update_my_medical_profile(
    profile_in: PatientMedicalProfileUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    return await crud_patient.update_profile(db, current_user.id, profile_in)

@router.get(
    "/{patient_id}/medical-profile",
    response_model=PatientMedicalProfileResponse,
    summary="Staff (Doctor / Compounder) views patient's complete medical history",
    dependencies=[Depends(require_permissions(["vitals:read", "consultations:read"]))],
)
async def get_patient_medical_profile(
    patient_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    profile = await crud_patient.get_or_create_profile(db, patient_id)
    return profile
