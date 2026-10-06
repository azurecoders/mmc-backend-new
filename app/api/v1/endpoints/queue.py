from datetime import date
from typing import Annotated, List, Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment
from app.models.queue import QueueEntry
from app.api.deps import (
    get_current_user,
    get_db,
    require_permissions,
)
from app.core.socket_manager import socket_manager
from app.crud.crud_appointment import crud_appointment
from app.crud.crud_doctor import crud_doctor
from app.crud.crud_queue import crud_queue
from app.models.user import User
from app.schemas.auth import MessageResponse
from app.schemas.queue import (
    DoctorLiveQueueSummary,
    PatientLiveQueueStatus,
    QueueCallPatientRequest,
    QueueCheckInRequest,
    QueueEntryResponse,
    WaitingRoomTVDisplay,
)

router = APIRouter()

async def _broadcast_queue_state(db: AsyncSession, doctor_id: uuid.UUID, queue_date: date):
    """Helper to recalculate and broadcast updated queue state across all Socket.IO rooms."""
    doc_summary = await crud_queue.get_doctor_live_summary(db, doctor_id, queue_date)
    tv_summary = await crud_queue.get_tv_display_summary(db, queue_date)
    await socket_manager.emit_queue_change(
        doctor_id=doctor_id,
        doctor_summary=doc_summary.model_dump(mode="json"),
        waiting_room_summary=tv_summary.model_dump(mode="json"),
    )

@router.post(
    "/check-in",
    response_model=QueueEntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Compounder checks an approved appointment into today's live queue",
    dependencies=[Depends(require_permissions(["queue:manage"]))],
)
async def check_in_patient(
    checkin_in: QueueCheckInRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    appointment = await crud_appointment.get_by_id(db, checkin_in.appointment_id)
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )
    if appointment.status not in ["APPROVED", "PENDING_APPROVAL"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot check in appointment in '{appointment.status}' status. Must be APPROVED.",
        )

    queue_entry = await crud_queue.check_in(
        db, appointment=appointment, is_priority=checkin_in.is_priority
    )

    # Broadcast real-time update
    await _broadcast_queue_state(db, queue_entry.doctor_id, queue_entry.queue_date)

    # Notify patient of their initial queue position
    patient_status = await crud_queue.get_patient_live_status(db, queue_entry)
    await socket_manager.emit_patient_status_update(
        patient_id=queue_entry.patient_id,
        appointment_id=queue_entry.appointment_id,
        status_payload=patient_status.model_dump(mode="json"),
    )

    return queue_entry

@router.post(
    "/call-patient",
    response_model=QueueEntryResponse,
    summary="Compounder or Doctor activates patient turn (real-time alert to Patient & Doctor)",
    dependencies=[Depends(require_permissions(["queue:call_patient"]))],
)
async def call_patient(
    call_in: QueueCallPatientRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """
    Sets patient account/token status to CALLED_IN.
    Instantly triggers Socket.IO event 'queue:your_turn' to patient and doctor screen.
    """
    queue_entry: Optional[QueueEntry] = None

    if call_in.queue_entry_id:
        queue_entry = await crud_queue.get_by_id(db, call_in.queue_entry_id)
        if not queue_entry:
            # Check if this ID is an appointment ID
            stmt_apt = select(Appointment).where(Appointment.id == call_in.queue_entry_id)
            res_apt = await db.execute(stmt_apt)
            apt = res_apt.scalar_one_or_none()
            if apt:
                existing_qe = await crud_queue.get_by_appointment_id(db, apt.id)
                if existing_qe:
                    queue_entry = existing_qe
                else:
                    queue_entry = await crud_queue.check_in(db, appointment=apt)

    if not queue_entry and call_in.doctor_id:
        # Find next waiting patient in queue for this doctor today
        today = date.today()
        stmt_next = (
            select(QueueEntry)
            .where(
                QueueEntry.doctor_id == call_in.doctor_id,
                QueueEntry.queue_date == today,
                QueueEntry.status == "WAITING",
            )
            .order_by(QueueEntry.is_priority.desc(), QueueEntry.token_number.asc())
        )
        res_next = await db.execute(stmt_next)
        queue_entry = res_next.scalars().first()

        if not queue_entry:
            # Check if there is an approved appointment for today not yet checked in
            stmt_apt = (
                select(Appointment)
                .where(
                    Appointment.doctor_id == call_in.doctor_id,
                    Appointment.appointment_date == today,
                    Appointment.status.in_(["APPROVED", "CHECKED_IN", "PENDING_APPROVAL"]),
                )
                .order_by(Appointment.token_number.asc())
            )
            res_apts = await db.execute(stmt_apt)
            today_apts = res_apts.scalars().all()
            for a in today_apts:
                existing_qe = await crud_queue.get_by_appointment_id(db, a.id)
                if not existing_qe:
                    queue_entry = await crud_queue.check_in(db, appointment=a)
                    break
                elif existing_qe.status == "WAITING":
                    queue_entry = existing_qe
                    break

    if not queue_entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No patients currently waiting in queue for this doctor.",
        )

    if queue_entry.status in ["COMPLETED", "CANCELLED"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot call patient with status '{queue_entry.status}'.",
        )

    updated_entry = await crud_queue.call_patient(
        db, queue_entry=queue_entry, called_by_user_id=current_user.id
    )

    # Fetch updated patient status
    patient_status = await crud_queue.get_patient_live_status(db, updated_entry)
    doctor = updated_entry.doctor
    doctor_name = doctor.user.full_name if (doctor and doctor.user) else "Doctor"
    room_number = doctor.room_number if doctor else "Cabin"
    patient_name = updated_entry.patient.full_name if updated_entry.patient else "Patient"

    call_payload = {
        "appointment_id": str(updated_entry.appointment_id),
        "queue_entry_id": str(updated_entry.id),
        "token_number": updated_entry.token_number,
        "patient_name": patient_name,
        "doctor_id": str(updated_entry.doctor_id),
        "doctor_name": doctor_name,
        "room_number": room_number,
        "message": f"Token #{updated_entry.token_number} ({patient_name}): Please proceed to {room_number}",
        "called_at": str(updated_entry.called_in_time),
    }

    # 1. Instant alert to Patient & Doctor via Socket.IO
    await socket_manager.emit_turn_called(
        patient_id=updated_entry.patient_id,
        appointment_id=updated_entry.appointment_id,
        doctor_id=updated_entry.doctor_id,
        call_payload=call_payload,
    )

    # 2. Broadcast updated queue counts to Doctor Cabin, TV Screens & Compounder
    await _broadcast_queue_state(db, updated_entry.doctor_id, updated_entry.queue_date)

    return updated_entry

@router.post(
    "/{queue_entry_id}/start-session",
    response_model=QueueEntryResponse,
    summary="Doctor marks consultation started",
    dependencies=[Depends(require_permissions(["consultations:create"]))],
)
async def start_consultation(
    queue_entry_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    queue_entry = await crud_queue.get_by_id(db, queue_entry_id)
    if not queue_entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Queue entry not found",
        )
    updated = await crud_queue.start_consultation(db, queue_entry)
    await _broadcast_queue_state(db, updated.doctor_id, updated.queue_date)
    return updated

@router.post(
    "/{queue_entry_id}/complete-session",
    response_model=QueueEntryResponse,
    summary="Doctor finishes consultation",
    dependencies=[Depends(require_permissions(["consultations:update"]))],
)
async def complete_consultation(
    queue_entry_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    queue_entry = await crud_queue.get_by_id(db, queue_entry_id)
    if not queue_entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Queue entry not found",
        )
    updated = await crud_queue.complete_consultation(db, queue_entry)
    await _broadcast_queue_state(db, updated.doctor_id, updated.queue_date)
    return updated

@router.post(
    "/{queue_entry_id}/hold",
    response_model=QueueEntryResponse,
    summary="Put patient on hold (stepped out / waiting for test)",
    dependencies=[Depends(require_permissions(["queue:manage"]))],
)
async def hold_patient(
    queue_entry_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    queue_entry = await crud_queue.get_by_id(db, queue_entry_id)
    if not queue_entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Queue entry not found",
        )
    updated = await crud_queue.hold_patient(db, queue_entry)
    await _broadcast_queue_state(db, updated.doctor_id, updated.queue_date)
    return updated

@router.get(
    "/patient-status/{appointment_id}",
    response_model=PatientLiveQueueStatus,
    summary="Patient live queue status (token number, people ahead, estimated wait time)",
    dependencies=[Depends(require_permissions(["queue:read"]))],
)
async def get_patient_live_status(
    appointment_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """
    Returns personal live queue tracker:
    - Your Token Number
    - Currently Serving Token
    - Number of Patients Ahead
    - Estimated Wait Time (minutes)
    - Doctor Cabin / Room Number
    - Is Your Turn (True/False)
    """
    queue_entry = await crud_queue.get_by_appointment_id(db, appointment_id)
    if not queue_entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient is not yet checked into the live queue for this appointment.",
        )
    return await crud_queue.get_patient_live_status(db, queue_entry)

@router.get(
    "/doctor-queue/{doctor_id}",
    response_model=DoctorLiveQueueSummary,
    summary="Doctor cabin live queue summary",
    dependencies=[Depends(require_permissions(["queue:read"]))],
)
async def get_doctor_live_summary(
    doctor_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    queue_date: Optional[date] = Query(None, description="Defaults to today"),
):
    today = queue_date or date.today()
    return await crud_queue.get_doctor_live_summary(db, doctor_id, today)

@router.get(
    "/doctor-queue/{doctor_id}/entries",
    response_model=List[QueueEntryResponse],
    summary="List all patient entries in doctor's queue today",
    dependencies=[Depends(require_permissions(["queue:read"]))],
)
async def get_doctor_queue_entries(
    doctor_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    queue_date: Optional[date] = Query(None, description="Defaults to today"),
):
    today = queue_date or date.today()
    return await crud_queue.get_doctor_queue_entries(db, doctor_id, today)

@router.get(
    "/tv-display",
    response_model=WaitingRoomTVDisplay,
    summary="Public display feed for Waiting Room TV monitors",
)
async def get_waiting_room_tv_display(
    db: Annotated[AsyncSession, Depends(get_db)],
    queue_date: Optional[date] = Query(None, description="Defaults to today"),
):
    """
    Feed for hospital wall-mounted TV screens showing currently active tokens and doctor cabins.
    """
    today = queue_date or date.today()
    return await crud_queue.get_tv_display_summary(db, today)
