import uuid
from datetime import date
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_db,
    require_permissions,
)
from app.crud.crud_appointment import crud_appointment
from app.crud.crud_department import crud_department
from app.crud.crud_doctor import crud_doctor
from app.crud.crud_role import crud_role
from app.crud.crud_user import crud_user
from app.models.user import User
from app.schemas.appointment import (
    AIRecommendDoctorsRequest,
    AIRecommendDoctorsResponse,
    AppointmentApproveRequest,
    AppointmentOnlineBooking,
    AppointmentRejectRequest,
    AppointmentResponse,
    AppointmentWalkinBooking,
)
from app.schemas.auth import MessageResponse
from app.schemas.user import UserCreate
from app.services.ai_recommender import ai_recommender_service

router = APIRouter()

@router.post(
    "/recommend-doctors",
    response_model=AIRecommendDoctorsResponse,
    summary="AI Department & Doctor Recommendation based on symptoms (using Gemma)",
)
async def recommend_doctors(
    request_in: AIRecommendDoctorsRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """
    Takes patient symptoms, duration, and severity, then uses 'gemma-4-31b-it'
    (with clinical heuristic fallback) to analyze the case and recommend:
    1. The appropriate hospital department / specialization
    2. Urgency level (Routine, Urgent, Emergency)
    3. Clinical triage summary
    4. Top matching doctors in the hospital with consultation fees, qualifications, and match rationale.
    """
    departments = await crud_department.get_multi(db, limit=50, active_only=True)
    doctors = await crud_doctor.get_multi(db, limit=100, available_only=True)

    if not departments or not doctors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Hospital departments or doctors directory is empty. Please contact administration.",
        )

    recommendations = await ai_recommender_service.recommend_doctors(
        symptoms=request_in.symptoms,
        duration=request_in.duration,
        severity=request_in.severity,
        departments=departments,
        doctors=doctors,
    )
    return recommendations

@router.post(
    "/book-online",
    response_model=AppointmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Patient books an appointment online (assigned token, awaits compounder approval)",
    dependencies=[Depends(require_permissions(["appointments:create"]))],
)
async def book_online(
    booking_in: AppointmentOnlineBooking,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """
    Online booking endpoint. Generates a sequential daily token number for the doctor,
    records symptoms and AI recommendation metadata, and sets status to PENDING_APPROVAL.
    """
    # Verify doctor exists and is available
    doctor = await crud_doctor.get_by_id(db, booking_in.doctor_id)
    if not doctor or not doctor.is_available:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Selected doctor is not available or does not exist.",
        )

    # Get sequential token number for today/requested date
    token_num = await crud_appointment.get_next_token_number(
        db, doctor_id=booking_in.doctor_id, appointment_date=booking_in.appointment_date
    )

    appointment = await crud_appointment.create_online(
        db,
        patient_id=current_user.id,
        obj_in=booking_in,
        token_number=token_num,
    )
    return appointment

@router.post(
    "/book-walkin",
    response_model=AppointmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Compounder registers a walk-in patient and creates approved appointment with token",
    dependencies=[Depends(require_permissions(["appointments:approve"]))],
)
async def book_walkin(
    booking_in: AppointmentWalkinBooking,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """
    Rapid walk-in registration by Compounder.
    If 'walkin_patient' details are provided, creates the patient user account on the fly.
    Assigns sequential token immediately and marks appointment as APPROVED.
    """
    # Determine or create patient
    patient_id = booking_in.patient_id
    if not patient_id:
        if not booking_in.walkin_patient:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Must provide either existing patient_id or walkin_patient details.",
            )
        
        # Check if patient phone/email already registered
        wp = booking_in.walkin_patient
        existing_user = None
        if wp.phone:
            existing_user = await crud_user.get_by_phone(db, wp.phone)
        if not existing_user and wp.email:
            existing_user = await crud_user.get_by_email(db, wp.email)

        if existing_user:
            patient_id = existing_user.id
        else:
            # Register new patient
            patient_role = await crud_role.get_by_code(db, "PATIENT")
            temp_email = wp.email or f"walkin_{uuid.uuid4().hex[:8]}@hospital-internal.com"
            user_in = UserCreate(
                email=temp_email,
                phone=wp.phone,
                full_name=wp.full_name,
                password=f"WalkinPass_{uuid.uuid4().hex[:6]}",
            )
            new_patient = await crud_user.create(
                db, obj_in=user_in, roles=[patient_role] if patient_role else []
            )
            patient_id = new_patient.id

    # Verify doctor
    doctor = await crud_doctor.get_by_id(db, booking_in.doctor_id)
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor not found.",
        )

    appointment = await crud_appointment.create_walkin(
        db,
        patient_id=patient_id,
        doctor_id=booking_in.doctor_id,
        chief_complaint=booking_in.chief_complaint,
        compounder_id=current_user.id,
        appointment_date=booking_in.appointment_date,
        slot_time=booking_in.slot_time,
        symptom_duration=booking_in.symptom_duration,
        severity=booking_in.severity,
    )
    return appointment

@router.get(
    "/",
    response_model=List[AppointmentResponse],
    summary="List appointments (role-aware: patient sees own, doctor sees their queue, compounder sees all)",
    dependencies=[Depends(require_permissions(["appointments:read"]))],
)
async def list_appointments(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    doctor_id: Optional[uuid.UUID] = Query(None),
    patient_id: Optional[uuid.UUID] = Query(None),
    appointment_date: Optional[date] = Query(None),
    status: Optional[str] = Query(None),
    booking_type: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    user_roles = {r.code for r in current_user.roles}

    # If user is only a patient, restrict to their own appointments
    if "PATIENT" in user_roles and "SUPER_ADMIN" not in user_roles and "COMPOUNDER" not in user_roles:
        patient_id = current_user.id

    # If user is doctor and not admin, default to their doctor profile
    if "DOCTOR" in user_roles and "SUPER_ADMIN" not in user_roles and "COMPOUNDER" not in user_roles:
        doc_profile = await crud_doctor.get_by_user_id(db, current_user.id)
        if doc_profile:
            doctor_id = doc_profile.id

    return await crud_appointment.get_multi(
        db,
        skip=skip,
        limit=limit,
        patient_id=patient_id,
        doctor_id=doctor_id,
        appointment_date=appointment_date,
        status=status,
        booking_type=booking_type,
    )

@router.get(
    "/pending-approvals",
    response_model=List[AppointmentResponse],
    summary="List pending online appointments awaiting compounder verification",
    dependencies=[Depends(require_permissions(["appointments:approve"]))],
)
async def list_pending_approvals(
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    return await crud_appointment.get_multi(
        db, skip=skip, limit=limit, status="PENDING_APPROVAL"
    )

@router.get(
    "/{appointment_id}",
    response_model=AppointmentResponse,
    summary="Get appointment details",
    dependencies=[Depends(require_permissions(["appointments:read"]))],
)
async def get_appointment(
    appointment_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    appointment = await crud_appointment.get_by_id(db, appointment_id)
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )
    return appointment

@router.post(
    "/{appointment_id}/approve",
    response_model=AppointmentResponse,
    summary="Compounder verifies and approves an appointment",
    dependencies=[Depends(require_permissions(["appointments:approve"]))],
)
async def approve_appointment(
    appointment_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    approve_in: Optional[AppointmentApproveRequest] = None,
):
    appointment = await crud_appointment.get_by_id(db, appointment_id)
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )
    if appointment.status != "PENDING_APPROVAL":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot approve appointment in status '{appointment.status}'. Must be PENDING_APPROVAL.",
        )

    updated = await crud_appointment.approve(db, appointment=appointment, compounder_id=current_user.id)
    return updated

@router.post(
    "/{appointment_id}/reject",
    response_model=AppointmentResponse,
    summary="Compounder rejects an appointment with reason",
    dependencies=[Depends(require_permissions(["appointments:approve"]))],
)
async def reject_appointment(
    appointment_id: uuid.UUID,
    reject_in: AppointmentRejectRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    appointment = await crud_appointment.get_by_id(db, appointment_id)
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )
    if appointment.status not in ["PENDING_APPROVAL", "APPROVED"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reject appointment in status '{appointment.status}'.",
        )

    updated = await crud_appointment.reject(
        db,
        appointment=appointment,
        compounder_id=current_user.id,
        reason=reject_in.rejection_reason,
    )
    return updated

@router.post(
    "/{appointment_id}/cancel",
    response_model=MessageResponse,
    summary="Cancel an appointment",
    dependencies=[Depends(require_permissions(["appointments:cancel"]))],
)
async def cancel_appointment(
    appointment_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    appointment = await crud_appointment.get_by_id(db, appointment_id)
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )
    user_roles = {r.code for r in current_user.roles}
    if "PATIENT" in user_roles and "SUPER_ADMIN" not in user_roles and "COMPOUNDER" not in user_roles:
        if appointment.patient_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot cancel another patient's appointment.",
            )

    appointment.status = "CANCELLED"
    db.add(appointment)
    await db.commit()
    return MessageResponse(message=f"Appointment {appointment.appointment_number} has been cancelled.")
