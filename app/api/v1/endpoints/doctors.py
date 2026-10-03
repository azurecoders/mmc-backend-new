import uuid
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permissions
from app.crud.crud_department import crud_department
from app.crud.crud_doctor import crud_doctor
from app.crud.crud_user import crud_user
from app.schemas.doctor import (
    DoctorProfileCreate,
    DoctorProfileResponse,
    DoctorProfileUpdate,
    DoctorScheduleCreate,
    DoctorScheduleResponse,
)

router = APIRouter()

@router.get(
    "/",
    response_model=List[DoctorProfileResponse],
    summary="List doctors directory with departments and consultation fees",
)
async def list_doctors(
    db: Annotated[AsyncSession, Depends(get_db)],
    department_id: Optional[uuid.UUID] = Query(None, description="Filter by department ID"),
    available_only: bool = Query(False, description="Filter only available doctors"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    """
    Returns directory of doctors with their qualifications, fees, room numbers, and schedules.
    """
    return await crud_doctor.get_multi(
        db, skip=skip, limit=limit, department_id=department_id, available_only=available_only
    )

@router.post(
    "/",
    response_model=DoctorProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new doctor profile",
    dependencies=[Depends(require_permissions(["users:create"]))],
)
async def create_doctor(
    doctor_in: DoctorProfileCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Validate user exists
    user = await crud_user.get_by_id(db, doctor_in.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User account for doctor not found.",
        )

    # Check if user already has a doctor profile
    existing_profile = await crud_doctor.get_by_user_id(db, doctor_in.user_id)
    if existing_profile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Doctor profile already exists for this user account.",
        )

    # Validate department exists
    dept = await crud_department.get_by_id(db, doctor_in.department_id)
    if not dept:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Department not found.",
        )

    return await crud_doctor.create(db, obj_in=doctor_in)

@router.get(
    "/{doctor_id}",
    response_model=DoctorProfileResponse,
    summary="Get doctor profile details and schedules",
)
async def get_doctor(
    doctor_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    doctor = await crud_doctor.get_by_id(db, doctor_id)
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor profile not found.",
        )
    return doctor

@router.put(
    "/{doctor_id}",
    response_model=DoctorProfileResponse,
    summary="Update doctor profile",
    dependencies=[Depends(require_permissions(["users:update"]))],
)
async def update_doctor(
    doctor_id: uuid.UUID,
    doctor_update: DoctorProfileUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    doctor = await crud_doctor.get_by_id(db, doctor_id)
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor profile not found.",
        )
    if doctor_update.department_id:
        dept = await crud_department.get_by_id(db, doctor_update.department_id)
        if not dept:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Department not found.",
            )

    return await crud_doctor.update(db, db_obj=doctor, obj_in=doctor_update)

@router.post(
    "/{doctor_id}/schedules",
    response_model=DoctorScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a weekly schedule slot to doctor",
    dependencies=[Depends(require_permissions(["users:update"]))],
)
async def add_doctor_schedule(
    doctor_id: uuid.UUID,
    schedule_in: DoctorScheduleCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    doctor = await crud_doctor.get_by_id(db, doctor_id)
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor profile not found.",
        )
    return await crud_doctor.add_schedule(db, doctor_id=doctor_id, obj_in=schedule_in)
