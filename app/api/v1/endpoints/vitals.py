import uuid
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.deps import (
    get_current_user,
    get_db,
    require_permissions,
)
from app.core.socket_manager import socket_manager
from app.crud.crud_doctor import crud_doctor
from app.crud.crud_patient import crud_patient
from app.crud.crud_user import crud_user
from app.models.doctor import DoctorProfile
from app.models.user import User
from app.schemas.patient import (
    CompounderVitalsIntakeCreate,
    DoctorCriticalAlertItem,
    PatientSelfVitalsLogCreate,
    PatientVitalsLogResponse,
)

router = APIRouter()

@router.post(
    "/patient-log",
    response_model=PatientVitalsLogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Patient self-records vital signs; AI analyzes criticality against medical history and alerts doctor if critical",
)
async def log_patient_self_vitals(
    vitals_in: PatientSelfVitalsLogCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """
    Patient submits their vital signs from the self-care portal.
    1. Evaluates vitals using MEWS / NEWS2 augmented by AI with the patient's full medical history.
    2. If critical, automatically identifies their primary consultant doctor and sends a high-priority real-time alert.
    """
    vitals_log = await crud_patient.record_patient_self_vitals(
        db, patient_id=current_user.id, vitals_in=vitals_in
    )

    # If critical, send real-time alert to the attending doctor
    if vitals_log.is_critical and vitals_log.notified_doctor_id:
        alert_payload = {
            "vitals_log_id": str(vitals_log.id),
            "patient_id": str(current_user.id),
            "patient_name": current_user.full_name,
            "patient_phone": current_user.phone,
            "triage_level": vitals_log.triage_level,
            "mews_score": vitals_log.mews_score,
            "systolic_bp": vitals_log.systolic_bp,
            "diastolic_bp": vitals_log.diastolic_bp,
            "heart_rate": vitals_log.heart_rate,
            "spo2": vitals_log.spo2,
            "temperature_f": vitals_log.temperature_f,
            "symptoms_notes": vitals_log.symptoms_notes,
            "ai_analysis": vitals_log.ai_analysis,
            "clinical_recommendation": vitals_log.clinical_recommendation,
            "risk_factors_detected": vitals_log.risk_factors_detected,
            "recorded_at": str(vitals_log.created_at),
        }
        await socket_manager.emit_critical_vitals_alert(
            doctor_id=vitals_log.notified_doctor_id,
            patient_id=current_user.id,
            alert_payload=alert_payload,
        )

    # Attach doctor name for friendly response if notified
    doc_name = None
    if vitals_log.notified_doctor:
        doc_name = vitals_log.notified_doctor.user.full_name if vitals_log.notified_doctor.user else "Consultant"

    resp = PatientVitalsLogResponse.model_validate(vitals_log)
    resp.doctor_name = doc_name
    return resp


@router.post(
    "/compounder-intake",
    response_model=PatientVitalsLogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Compounder records patient vitals during triage; AI calculates MEWS and escalates priority if critical",
    dependencies=[Depends(require_permissions(["vitals:create"]))],
)
async def record_compounder_vitals_intake(
    intake_in: CompounderVitalsIntakeCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """
    Compounder inputs vitals at clinic triage.
    1. AI computes MEWS / NEWS and evaluates risk in light of patient medical history.
    2. If critical, automatically elevates the queue token to PRIORITY and alerts doctor cabin.
    """
    try:
        vitals_log = await crud_patient.record_compounder_intake_vitals(
            db, compounder_id=current_user.id, intake_in=intake_in
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    if vitals_log.is_critical and vitals_log.notified_doctor_id:
        escalation_payload = {
            "appointment_id": str(intake_in.appointment_id),
            "patient_id": str(vitals_log.patient_id),
            "vitals_log_id": str(vitals_log.id),
            "triage_level": vitals_log.triage_level,
            "mews_score": vitals_log.mews_score,
            "is_priority": True,
            "ai_analysis": vitals_log.ai_analysis,
            "clinical_recommendation": vitals_log.clinical_recommendation,
            "message": f"EMERGENCY PRIORITY: Patient exhibiting acute physiological distress (MEWS: {vitals_log.mews_score}).",
        }
        await socket_manager.emit_queue_priority_escalation(
            doctor_id=vitals_log.notified_doctor_id,
            escalation_payload=escalation_payload,
        )

    return vitals_log


@router.get(
    "/patient/{patient_id}/history",
    response_model=List[PatientVitalsLogResponse],
    summary="Get vitals history timeline for a patient",
)
async def get_patient_vitals_history(
    patient_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(50, ge=1, le=100),
):
    # Patient can view their own history; staff (Doctor, Compounder, Admin) can view any patient's vitals
    user_roles = {r.code for r in current_user.roles}
    user_permissions = await crud_user.get_effective_permissions(db, current_user)
    is_self = (current_user.id == patient_id)
    has_staff_access = (
        "*" in user_permissions
        or "vitals:read" in user_permissions
        or bool(user_roles & {"DOCTOR", "COMPOUNDER", "SUPER_ADMIN"})
    )
    if not is_self and not has_staff_access:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    return await crud_patient.get_vitals_history(db, patient_id=patient_id, limit=limit)


@router.get(
    "/patient/{patient_id}/latest",
    response_model=Optional[PatientVitalsLogResponse],
    summary="Get latest vitals recorded for a patient",
)
async def get_patient_latest_vitals(
    patient_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    user_roles = {r.code for r in current_user.roles}
    user_permissions = await crud_user.get_effective_permissions(db, current_user)
    is_self = (current_user.id == patient_id)
    has_staff_access = (
        "*" in user_permissions
        or "vitals:read" in user_permissions
        or bool(user_roles & {"DOCTOR", "COMPOUNDER", "SUPER_ADMIN"})
    )
    if not is_self and not has_staff_access:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    history = await crud_patient.get_vitals_history(db, patient_id=patient_id, limit=1)
    return history[0] if history else None


@router.get(
    "/doctor/critical-alerts",
    response_model=List[DoctorCriticalAlertItem],
    summary="Doctor views pending critical vitals alerts assigned to them",
    dependencies=[Depends(require_permissions(["consultations:read"]))],
)
async def get_doctor_critical_alerts(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    stmt = select(DoctorProfile).where(DoctorProfile.user_id == current_user.id)
    res = await db.execute(stmt)
    doc_profile = res.scalar_one_or_none()
    if not doc_profile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current user is not registered as a doctor profile.",
        )

    alerts = await crud_patient.get_doctor_critical_alerts(db, doctor_id=doc_profile.id)
    result: List[DoctorCriticalAlertItem] = []
    for a in alerts:
        p_name = a.patient.full_name if a.patient else "Patient"
        p_phone = a.patient.phone if a.patient else None
        result.append(
            DoctorCriticalAlertItem(
                vitals_log_id=a.id,
                patient_id=a.patient_id,
                patient_name=p_name,
                patient_phone=p_phone,
                appointment_id=a.appointment_id,
                triage_level=a.triage_level,
                is_critical=a.is_critical,
                mews_score=a.mews_score,
                systolic_bp=a.systolic_bp,
                diastolic_bp=a.diastolic_bp,
                heart_rate=a.heart_rate,
                spo2=a.spo2,
                temperature_f=a.temperature_f,
                symptoms_notes=a.symptoms_notes,
                ai_analysis=a.ai_analysis,
                clinical_recommendation=a.clinical_recommendation,
                risk_factors_detected=a.risk_factors_detected,
                recorded_at=a.created_at,
                acknowledged=a.doctor_alert_acknowledged,
            )
        )
    return result


@router.post(
    "/alerts/{vitals_log_id}/acknowledge",
    summary="Doctor acknowledges critical vitals alert",
    dependencies=[Depends(require_permissions(["consultations:read"]))],
)
async def acknowledge_critical_alert(
    vitals_log_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    stmt = select(DoctorProfile).where(DoctorProfile.user_id == current_user.id)
    res = await db.execute(stmt)
    doc_profile = res.scalar_one_or_none()
    if not doc_profile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current user is not registered as a doctor profile.",
        )

    updated = await crud_patient.acknowledge_doctor_alert(
        db, vitals_log_id=vitals_log_id, doctor_id=doc_profile.id
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Critical alert not found or does not belong to this doctor.",
        )
    return {"status": "acknowledged", "vitals_log_id": str(vitals_log_id)}
