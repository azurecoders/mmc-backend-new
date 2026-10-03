from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.models.appointment import Appointment
from app.models.consultation import Consultation
from app.models.doctor import DoctorProfile
from app.models.patient import PatientMedicalProfile, PatientVitalsLog
from app.models.queue import QueueEntry
from app.schemas.patient import (
    CompounderVitalsIntakeCreate,
    PatientMedicalProfileUpdate,
    PatientSelfVitalsLogCreate,
)
from app.services.ai_triage import ai_triage_service

class CRUDPatient:
    async def get_or_create_profile(
        self, db: AsyncSession, patient_id: uuid.UUID
    ) -> PatientMedicalProfile:
        stmt = select(PatientMedicalProfile).where(PatientMedicalProfile.patient_id == patient_id)
        result = await db.execute(stmt)
        profile = result.scalar_one_or_none()
        if not profile:
            profile = PatientMedicalProfile(
                patient_id=patient_id,
                chronic_conditions=[],
                known_allergies=[],
                past_surgeries=[],
                ongoing_medications=[],
                family_medical_history=[],
                lifestyle_factors={},
            )
            db.add(profile)
            await db.commit()
            await db.refresh(profile)
        return profile

    async def get_profile_by_patient_id(
        self, db: AsyncSession, patient_id: uuid.UUID
    ) -> Optional[PatientMedicalProfile]:
        stmt = select(PatientMedicalProfile).where(PatientMedicalProfile.patient_id == patient_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_profile(
        self, db: AsyncSession, patient_id: uuid.UUID, obj_in: PatientMedicalProfileUpdate
    ) -> PatientMedicalProfile:
        profile = await self.get_or_create_profile(db, patient_id)
        update_data = obj_in.model_dump(exclude_unset=True)

        # Convert nested pydantic models to dicts if present
        for field in [
            "chronic_conditions",
            "known_allergies",
            "past_surgeries",
            "ongoing_medications",
            "family_medical_history",
        ]:
            if field in update_data and update_data[field] is not None:
                update_data[field] = [
                    item if isinstance(item, dict) else item.model_dump()
                    for item in update_data[field]
                ]

        if "lifestyle_factors" in update_data and update_data["lifestyle_factors"] is not None:
            lf = update_data["lifestyle_factors"]
            update_data["lifestyle_factors"] = lf if isinstance(lf, dict) else lf.model_dump()

        for k, v in update_data.items():
            setattr(profile, k, v)

        db.add(profile)
        await db.commit()
        await db.refresh(profile)
        return profile

    async def find_primary_consultant_for_patient(
        self, db: AsyncSession, patient_id: uuid.UUID
    ) -> Optional[DoctorProfile]:
        """
        Locates the patient's primary consulting physician.
        First checks most recent finalized Consultation, then upcoming Appointment.
        """
        # 1. Most recent finalized consultation
        stmt_c = (
            select(Consultation)
            .where(Consultation.patient_id == patient_id, Consultation.is_finalized == True)
            .order_by(Consultation.created_at.desc())
            .options(joinedload(Consultation.doctor).joinedload(DoctorProfile.user))
            .limit(1)
        )
        res_c = await db.execute(stmt_c)
        recent_c = res_c.scalar_one_or_none()
        if recent_c and recent_c.doctor:
            return recent_c.doctor

        # 2. Latest active appointment
        stmt_a = (
            select(Appointment)
            .where(
                Appointment.patient_id == patient_id,
                Appointment.status.in_(["APPROVED", "CHECKED_IN", "IN_CONSULTATION"]),
            )
            .order_by(Appointment.appointment_date.desc(), Appointment.created_at.desc())
            .options(joinedload(Appointment.doctor).joinedload(DoctorProfile.user))
            .limit(1)
        )
        res_a = await db.execute(stmt_a)
        recent_a = res_a.scalar_one_or_none()
        if recent_a and recent_a.doctor:
            return recent_a.doctor

        return None

    async def record_patient_self_vitals(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
        vitals_in: PatientSelfVitalsLogCreate,
    ) -> PatientVitalsLog:
        """
        Patient self-records vitals from home/portal.
        AI evaluates values against patient's full medical history.
        If critical, consultant is automatically identified and linked for alert.
        """
        # 1. Fetch full medical history profile
        profile = await self.get_profile_by_patient_id(db, patient_id)
        profile_dict = profile.__dict__ if profile else None

        # 2. Fetch past consultations diagnoses
        stmt_past = (
            select(Consultation)
            .where(Consultation.patient_id == patient_id)
            .order_by(Consultation.created_at.desc())
            .limit(5)
        )
        res_past = await db.execute(stmt_past)
        past_consultations = [
            {"diagnosis": c.diagnosis, "clinical_notes": c.clinical_notes, "date": str(c.created_at)}
            for c in res_past.scalars().all()
        ]

        # 3. AI Triage Evaluation
        ai_eval = await ai_triage_service.evaluate_vitals_with_history(
            vitals=vitals_in.model_dump(),
            medical_profile=profile_dict,
            past_consultations=past_consultations,
        )

        # 4. Check if critical and locate primary consultant
        notified_doc_id = None
        notified_at = None
        if ai_eval["is_critical"]:
            consultant = await self.find_primary_consultant_for_patient(db, patient_id)
            if consultant:
                notified_doc_id = consultant.id
                notified_at = datetime.now(timezone.utc)

        vitals_log = PatientVitalsLog(
            patient_id=patient_id,
            recorded_by_id=patient_id,
            source="PATIENT_SELF_REPORT",
            appointment_id=None,
            systolic_bp=vitals_in.systolic_bp,
            diastolic_bp=vitals_in.diastolic_bp,
            heart_rate=vitals_in.heart_rate,
            respiratory_rate=vitals_in.respiratory_rate,
            temperature_f=vitals_in.temperature_f,
            spo2=vitals_in.spo2,
            blood_glucose=vitals_in.blood_glucose,
            consciousness_level=vitals_in.consciousness_level,
            symptoms_notes=vitals_in.symptoms_notes,
            mews_score=ai_eval["mews_score"],
            news2_score=ai_eval["news2_score"],
            triage_level=ai_eval["triage_level"],
            is_critical=ai_eval["is_critical"],
            ai_analysis=ai_eval["ai_analysis"],
            clinical_recommendation=ai_eval["clinical_recommendation"],
            risk_factors_detected=ai_eval["risk_factors_detected"],
            notified_doctor_id=notified_doc_id,
            doctor_notified_at=notified_at,
        )
        db.add(vitals_log)
        await db.commit()
        await db.refresh(vitals_log)
        return vitals_log

    async def record_compounder_intake_vitals(
        self,
        db: AsyncSession,
        compounder_id: uuid.UUID,
        intake_in: CompounderVitalsIntakeCreate,
    ) -> PatientVitalsLog:
        """
        Compounder records pre-consultation vitals at clinic check-in.
        AI calculates MEWS / NEWS and checks medical history.
        If critical, automatically elevates the queue entry to priority!
        """
        # Fetch appointment to get patient & doctor
        stmt_apt = select(Appointment).where(Appointment.id == intake_in.appointment_id)
        res_apt = await db.execute(stmt_apt)
        appointment = res_apt.scalar_one_or_none()
        if not appointment:
            raise ValueError(f"Appointment {intake_in.appointment_id} not found.")

        patient_id = appointment.patient_id
        doctor_id = appointment.doctor_id

        # Fetch medical profile & past consultations
        profile = await self.get_profile_by_patient_id(db, patient_id)
        profile_dict = profile.__dict__ if profile else None

        stmt_past = (
            select(Consultation)
            .where(Consultation.patient_id == patient_id)
            .order_by(Consultation.created_at.desc())
            .limit(5)
        )
        res_past = await db.execute(stmt_past)
        past_consultations = [
            {"diagnosis": c.diagnosis, "clinical_notes": c.clinical_notes, "date": str(c.created_at)}
            for c in res_past.scalars().all()
        ]

        # AI Triage Evaluation
        ai_eval = await ai_triage_service.evaluate_vitals_with_history(
            vitals=intake_in.model_dump(),
            medical_profile=profile_dict,
            past_consultations=past_consultations,
        )

        is_critical = ai_eval["is_critical"] or (intake_in.is_priority_override is True)

        # Automatically escalate queue entry to priority if critical
        if is_critical:
            stmt_q = select(QueueEntry).where(QueueEntry.appointment_id == appointment.id)
            res_q = await db.execute(stmt_q)
            q_entry = res_q.scalar_one_or_none()
            if q_entry and not q_entry.is_priority:
                q_entry.is_priority = True
                db.add(q_entry)

        vitals_log = PatientVitalsLog(
            patient_id=patient_id,
            recorded_by_id=compounder_id,
            source="COMPOUNDER_INTAKE",
            appointment_id=appointment.id,
            systolic_bp=intake_in.systolic_bp,
            diastolic_bp=intake_in.diastolic_bp,
            heart_rate=intake_in.heart_rate,
            respiratory_rate=intake_in.respiratory_rate,
            temperature_f=intake_in.temperature_f,
            spo2=intake_in.spo2,
            blood_glucose=intake_in.blood_glucose,
            consciousness_level=intake_in.consciousness_level,
            symptoms_notes=intake_in.symptoms_notes,
            mews_score=ai_eval["mews_score"],
            news2_score=ai_eval["news2_score"],
            triage_level=ai_eval["triage_level"],
            is_critical=is_critical,
            ai_analysis=ai_eval["ai_analysis"],
            clinical_recommendation=ai_eval["clinical_recommendation"],
            risk_factors_detected=ai_eval["risk_factors_detected"],
            notified_doctor_id=doctor_id,
            doctor_notified_at=datetime.now(timezone.utc) if is_critical else None,
        )
        db.add(vitals_log)
        await db.commit()
        await db.refresh(vitals_log)
        return vitals_log

    async def get_vitals_history(
        self, db: AsyncSession, patient_id: uuid.UUID, limit: int = 50
    ) -> List[PatientVitalsLog]:
        stmt = (
            select(PatientVitalsLog)
            .where(PatientVitalsLog.patient_id == patient_id)
            .order_by(PatientVitalsLog.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_doctor_critical_alerts(
        self, db: AsyncSession, doctor_id: uuid.UUID
    ) -> List[PatientVitalsLog]:
        stmt = (
            select(PatientVitalsLog)
            .where(
                PatientVitalsLog.notified_doctor_id == doctor_id,
                PatientVitalsLog.is_critical == True,
            )
            .order_by(PatientVitalsLog.created_at.desc())
            .options(
                joinedload(PatientVitalsLog.patient),
                joinedload(PatientVitalsLog.appointment),
            )
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def acknowledge_doctor_alert(
        self, db: AsyncSession, vitals_log_id: uuid.UUID, doctor_id: uuid.UUID
    ) -> Optional[PatientVitalsLog]:
        stmt = select(PatientVitalsLog).where(
            PatientVitalsLog.id == vitals_log_id,
            PatientVitalsLog.notified_doctor_id == doctor_id,
        )
        result = await db.execute(stmt)
        log = result.scalar_one_or_none()
        if log:
            log.doctor_alert_acknowledged = True
            log.doctor_acknowledged_at = datetime.now(timezone.utc)
            db.add(log)
            await db.commit()
            await db.refresh(log)
        return log

crud_patient = CRUDPatient()
