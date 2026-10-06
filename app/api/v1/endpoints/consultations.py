from datetime import date
from typing import Annotated, List, Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_db,
    require_permissions,
)
from app.core.socket_manager import socket_manager
from app.crud.crud_appointment import crud_appointment
from app.crud.crud_consultation import crud_consultation
from app.crud.crud_doctor import crud_doctor
from app.crud.crud_lab import crud_lab
from app.crud.crud_patient import crud_patient
from app.crud.crud_queue import crud_queue
from app.crud.crud_user import crud_user
from app.models.user import User
from app.schemas.consultation import (
    ConsultationCreate,
    ConsultationResponse,
    ConsultationUpdate,
    PrescriptionExplanationResponse,
    DrugSafetyCheckRequest,
    DrugSafetyCheckResponse,
    ClinicalCopilotRequest,
    ClinicalCopilotResponse,
    VoiceToSoapRequest,
    VoiceToSoapResponse,
    GenerateDietPlanRequest,
    PersonalizedDietPlanResponse,
)
from app.services.ai_prescription_explainer import ai_prescription_explainer
from app.services.ai_lifestyle_planner import ai_lifestyle_planner
from app.services.ai_clinical_workbench import AIClinicalWorkbenchService


router = APIRouter()

@router.post(
    "/",
    response_model=ConsultationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Doctor creates and finalizes consultation (prescriptions, clinical notes, lab orders)",
    dependencies=[Depends(require_permissions(["consultations:create"]))],
)
async def create_consultation(
    consultation_in: ConsultationCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """
    Doctor records consultation details:
    - Chief complaints, diagnosis, clinical assessment, special instructions, highlights.
    - Prescriptions: medicines with dosage, frequency, duration, instructions.
    - Diagnostic Lab Orders: blood tests, X-rays, imaging.
    - Real-Time Broadcast:
      1. Patient receives instant notification with prescription & notes.
      2. Pharmacy receives live order with medicines to dispense.
      3. Lab Assistant receives live order with tests to conduct.
      4. Queue entry and appointment marked COMPLETED.
    """
    # 1. Validate appointment
    appointment = await crud_appointment.get_by_id(db, consultation_in.appointment_id)
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )

    # Check if consultation already exists for this appointment
    existing_consultation = await crud_consultation.get_by_appointment_id(db, appointment.id)
    if existing_consultation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Consultation already recorded for this appointment.",
        )

    # Validate lab test IDs if specified
    for lo in consultation_in.lab_orders:
        test_obj = await crud_lab.get_test_by_id(db, lo.test_id)
        if not test_obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Lab test with ID '{lo.test_id}' not found.",
            )

    # Create consultation in DB
    consultation = await crud_consultation.create(
        db, appointment=appointment, obj_in=consultation_in
    )

    # Real-Time Socket.IO notifications
    doctor_name = consultation.doctor.user.full_name if (consultation.doctor and consultation.doctor.user) else "Doctor"
    patient_name = consultation.patient.full_name if consultation.patient else "Patient"
    room_no = consultation.doctor.room_number if consultation.doctor else "Cabin"

    consultation_summary = {
        "consultation_id": str(consultation.id),
        "appointment_id": str(appointment.id),
        "patient_id": str(appointment.patient_id),
        "patient_name": patient_name,
        "doctor_name": doctor_name,
        "room_number": room_no,
        "diagnosis": consultation.diagnosis,
        "clinical_notes": consultation.clinical_notes,
        "special_instructions": consultation.special_instructions,
        "highlights": consultation.highlights,
        "follow_up_date": str(consultation.follow_up_date) if consultation.follow_up_date else None,
        "prescriptions_count": len(consultation.prescription_items),
        "lab_orders_count": len(consultation.lab_orders),
    }

    # 1. Notify Patient
    await socket_manager.emit_consultation_completed(
        patient_id=appointment.patient_id,
        appointment_id=appointment.id,
        consultation_summary=consultation_summary,
    )

    # 2. Notify Pharmacy if medicines were prescribed
    if consultation.prescription_items:
        pharma_payload = {
            "consultation_id": str(consultation.id),
            "appointment_id": str(appointment.id),
            "patient_id": str(appointment.patient_id),
            "patient_name": patient_name,
            "doctor_name": doctor_name,
            "room_number": room_no,
            "medicines": [
                {
                    "item_id": str(p.id),
                    "name": p.medicine_name,
                    "dosage": p.dosage,
                    "frequency": p.frequency,
                    "duration": p.duration,
                    "instructions": p.instructions,
                    "dispense_status": p.dispense_status,
                }
                for p in consultation.prescription_items
            ],
            "prescribed_at": str(consultation.created_at),
        }
        await socket_manager.emit_prescription_to_pharmacy(pharma_payload)

    # 3. Notify Lab Assistant if diagnostic tests were ordered
    if consultation.lab_orders:
        lab_payload = {
            "consultation_id": str(consultation.id),
            "appointment_id": str(appointment.id),
            "patient_id": str(appointment.patient_id),
            "patient_name": patient_name,
            "doctor_name": doctor_name,
            "room_number": room_no,
            "orders": [
                {
                    "order_id": str(lo.id),
                    "test_name": lo.test.name if lo.test else "Lab Test",
                    "category": lo.test.category if lo.test else "GENERAL",
                    "urgency": lo.urgency,
                    "instructions": lo.instructions,
                    "status": lo.status,
                }
                for lo in consultation.lab_orders
            ],
            "ordered_at": str(consultation.created_at),
        }
        await socket_manager.emit_lab_orders_to_lab(lab_payload)

    # 4. Broadcast updated live queue state
    doc_summary = await crud_queue.get_doctor_live_summary(
        db, consultation.doctor_id, appointment.appointment_date
    )
    tv_summary = await crud_queue.get_tv_display_summary(db, appointment.appointment_date)
    await socket_manager.emit_queue_change(
        doctor_id=consultation.doctor_id,
        doctor_summary=doc_summary.model_dump(mode="json"),
        waiting_room_summary=tv_summary.model_dump(mode="json"),
    )

    return consultation

@router.get(
    "/{consultation_id}",
    response_model=ConsultationResponse,
    summary="Get full consultation details",
    dependencies=[Depends(require_permissions(["consultations:read"]))],
)
async def get_consultation(
    consultation_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    consultation = await crud_consultation.get_by_id(db, consultation_id)
    if not consultation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Consultation record not found",
        )
    return consultation

@router.get(
    "/appointment/{appointment_id}",
    response_model=ConsultationResponse,
    summary="Get consultation record for an appointment (patient prescription & notes)",
    dependencies=[Depends(require_permissions(["consultations:read"]))],
)
async def get_consultation_by_appointment(
    appointment_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    consultation = await crud_consultation.get_by_appointment_id(db, appointment_id)
    if not consultation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No consultation has been recorded yet for this appointment.",
        )
    return consultation

@router.get(
    "/patient/{patient_id}/history",
    response_model=List[ConsultationResponse],
    summary="Get full medical history of a patient (all past visits and prescriptions)",
    dependencies=[Depends(require_permissions(["consultations:read"]))],
)
async def get_patient_history(
    patient_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    user_roles = {r.code for r in current_user.roles}
    if "PATIENT" in user_roles and "SUPER_ADMIN" not in user_roles and "DOCTOR" not in user_roles:
        if patient_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot view another patient's medical history.",
            )

    return await crud_consultation.get_multi(
        db, skip=skip, limit=limit, patient_id=patient_id
    )

@router.put(
    "/{consultation_id}",
    response_model=ConsultationResponse,
    summary="Update consultation notes",
    dependencies=[Depends(require_permissions(["consultations:update"]))],
)
async def update_consultation(
    consultation_id: uuid.UUID,
    consultation_update: ConsultationUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    consultation = await crud_consultation.get_by_id(db, consultation_id)
    if not consultation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Consultation not found",
        )
    return await crud_consultation.update(db, db_obj=consultation, obj_in=consultation_update)

@router.post(
    "/{consultation_id}/explain-prescription",
    response_model=PrescriptionExplanationResponse,
    summary="AI Pharmacist assistant explains prescription in plain English using token-efficient OpenAI gpt-4o-mini",
)
async def explain_consultation_prescription(
    consultation_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    consultation = await crud_consultation.get_by_id(db, consultation_id)
    if not consultation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Consultation record not found.",
        )

    # Permission check: Patient can only explain their own prescription unless staff
    user_roles = {r.code for r in current_user.roles}
    user_permissions = await crud_user.get_effective_permissions(db, current_user)
    is_owner = (current_user.id == consultation.patient_id)
    has_staff_access = (
        "*" in user_permissions
        or "consultations:read" in user_permissions
        or bool(user_roles & {"DOCTOR", "COMPOUNDER", "SUPER_ADMIN"})
    )
    if not is_owner and not has_staff_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this consultation record.",
        )

    # Fetch patient's medical profile for allergy and condition checks
    profile = await crud_patient.get_profile_by_patient_id(db, consultation.patient_id)
    profile_dict = profile.__dict__ if profile else None

    return await ai_prescription_explainer.explain_prescription(
        consultation=consultation,
        medical_profile=profile_dict,
    )

@router.post(
    "/{consultation_id}/diet-lifestyle-plan",
    response_model=PersonalizedDietPlanResponse,
    summary="Generate personalized 7-day meal plan, foods to avoid, and hydration target based on consultation diagnosis",
)
async def generate_consultation_diet_lifestyle_plan(
    consultation_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    consultation = await crud_consultation.get_by_id(db, consultation_id)
    if not consultation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Consultation record not found.",
        )

    # Permission check: Patient can only generate for their own consultation unless staff
    user_roles = {r.code for r in current_user.roles}
    user_permissions = await crud_user.get_effective_permissions(db, current_user)
    is_owner = (current_user.id == consultation.patient_id)
    has_staff_access = (
        "*" in user_permissions
        or "consultations:read" in user_permissions
        or bool(user_roles & {"DOCTOR", "COMPOUNDER", "SUPER_ADMIN"})
    )
    if not is_owner and not has_staff_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this consultation record.",
        )

    # Fetch patient's medical profile
    profile = await crud_patient.get_profile_by_patient_id(db, consultation.patient_id)
    
    chronic_conditions: List[str] = []
    allergies: List[str] = []
    dietary_preferences: Optional[str] = None
    patient_age: Optional[int] = None
    patient_gender: Optional[str] = None

    if profile:
        if profile.chronic_conditions and isinstance(profile.chronic_conditions, list):
            chronic_conditions = [c.get("condition", "") for c in profile.chronic_conditions if isinstance(c, dict) and c.get("condition")]
        if profile.known_allergies and isinstance(profile.known_allergies, list):
            allergies = [a.get("allergen", "") for a in profile.known_allergies if isinstance(a, dict) and a.get("allergen")]
        if profile.lifestyle_factors and isinstance(profile.lifestyle_factors, dict):
            dietary_preferences = profile.lifestyle_factors.get("dietary_restrictions")
        if profile.date_of_birth:
            try:
                patient_age = datetime.now().year - profile.date_of_birth.year
            except Exception:
                pass
        patient_gender = profile.gender

    patient_name = consultation.patient.full_name if consultation.patient else current_user.full_name

    return await ai_lifestyle_planner.generate_diet_and_lifestyle_plan(
        patient_name=patient_name,
        diagnosis=consultation.diagnosis,
        chronic_conditions=chronic_conditions,
        allergies=allergies,
        dietary_preferences=dietary_preferences,
        consultation_id=consultation.id,
        patient_age=patient_age,
        patient_gender=patient_gender,
    )

@router.post(
    "/patient/me/diet-lifestyle-plan",
    response_model=PersonalizedDietPlanResponse,
    summary="Patient generates a personalized 7-day diet & lifestyle plan based on their active medical profile or preferences",
)
async def generate_my_diet_lifestyle_plan(
    req: GenerateDietPlanRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    profile = await crud_patient.get_profile_by_patient_id(db, current_user.id)
    
    chronic_conditions: List[str] = list(req.chronic_conditions or [])
    allergies: List[str] = list(req.allergies or [])
    dietary_preferences: Optional[str] = req.dietary_preferences
    patient_age: Optional[int] = req.patient_age
    patient_gender: Optional[str] = req.patient_gender
    diagnosis: str = req.diagnosis or ""

    if profile:
        if not chronic_conditions and profile.chronic_conditions and isinstance(profile.chronic_conditions, list):
            chronic_conditions = [c.get("condition", "") for c in profile.chronic_conditions if isinstance(c, dict) and c.get("condition")]
        if not allergies and profile.known_allergies and isinstance(profile.known_allergies, list):
            allergies = [a.get("allergen", "") for a in profile.known_allergies if isinstance(a, dict) and a.get("allergen")]
        if not dietary_preferences and profile.lifestyle_factors and isinstance(profile.lifestyle_factors, dict):
            dietary_preferences = profile.lifestyle_factors.get("dietary_restrictions")
        if patient_age is None and profile.date_of_birth:
            try:
                patient_age = datetime.now().year - profile.date_of_birth.year
            except Exception:
                pass
        if not patient_gender:
            patient_gender = profile.gender

    latest_consultation_id: Optional[uuid.UUID] = None
    if not diagnosis:
        history = await crud_consultation.get_multi(db, limit=1, patient_id=current_user.id)
        if history:
            diagnosis = history[0].diagnosis
            latest_consultation_id = history[0].id
        elif chronic_conditions:
            diagnosis = chronic_conditions[0]
        else:
            diagnosis = "General Cardiometabolic Wellness & Healthy Living"

    return await ai_lifestyle_planner.generate_diet_and_lifestyle_plan(
        patient_name=current_user.full_name,
        diagnosis=diagnosis,
        chronic_conditions=chronic_conditions,
        allergies=allergies,
        dietary_preferences=dietary_preferences,
        consultation_id=latest_consultation_id,
        patient_age=patient_age,
        patient_gender=patient_gender,
    )

# =====================================================================
# AI Clinical Workbench Endpoints (OpenAI gpt-4o-mini)
# =====================================================================

@router.post(
    "/ai/drug-safety-check",
    response_model=DrugSafetyCheckResponse,
    summary="Real-time Drug-Drug, Drug-Allergy & Drug-Disease Interaction Checker",
    dependencies=[Depends(require_permissions(["consultations:read"]))],
)
async def check_prescription_drug_safety(
    req: DrugSafetyCheckRequest,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """
    Evaluates prescribed medication list for:
    1. Drug-Drug pharmacokinetic & pharmacodynamic interactions.
    2. Drug-Allergy severe contraindications.
    3. Drug-Disease conflicts against chronic illnesses.
    """
    return await AIClinicalWorkbenchService.check_drug_safety(req)

@router.post(
    "/ai/clinical-copilot",
    response_model=ClinicalCopilotResponse,
    summary="AI Differential Diagnosis & Confirmatory Lab Test Recommender",
    dependencies=[Depends(require_permissions(["consultations:read"]))],
)
async def get_clinical_copilot_recommendations(
    req: ClinicalCopilotRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """
    Analyzes patient presentation, reported symptoms, and intake vitals to recommend:
    1. 2-3 prioritized differential diagnoses with likelihood and clinical rationale.
    2. Recommended confirmatory diagnostic laboratory panels.
    3. Red flag warning symptoms and recommended physical exam maneuvers.
    """
    catalog = await crud_lab.get_catalog(db)
    catalog_dicts = [{"id": str(c.id), "name": c.name, "category": c.category} for c in catalog]
    return await AIClinicalWorkbenchService.get_clinical_copilot_guidance(req, catalog_tests=catalog_dicts)

@router.post(
    "/ai/voice-to-soap",
    response_model=VoiceToSoapResponse,
    summary="Ambient Voice Dictation to Structured Clinical SOAP Notes Scribe",
    dependencies=[Depends(require_permissions(["consultations:create"]))],
)
async def convert_ambient_voice_to_soap(
    req: VoiceToSoapRequest,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """
    Converts raw clinical voice dictation or conversation transcripts into formal SOAP notes:
    - Subjective (HPI, chief complaint narrative)
    - Objective (physical examination & vitals)
    - Assessment (clinical impression & working diagnosis)
    - Plan (prescriptions, diagnostic orders, instructions)
    """
    return await AIClinicalWorkbenchService.convert_voice_to_soap(req)

