from datetime import date, datetime, timezone
import uuid
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from sqlalchemy import (
    String,
    Text,
    Integer,
    Float,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    JSON,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.base import TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.doctor import DoctorProfile
    from app.models.user import User

class PatientMedicalProfile(Base, TimestampMixin):
    """
    Comprehensive, long-term medical history archive for a patient.
    Captures chronic conditions, drug allergies, past surgeries, ongoing medications,
    family medical history, baseline vitals, and lifestyle metrics.
    """
    __tablename__ = "patient_medical_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=generate_uuid
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )

    # Core Biometrics
    blood_group: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # e.g., "O+", "A+", "B-"
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # MALE, FEMALE, OTHER
    height_cm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    baseline_systolic_bp: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    baseline_diastolic_bp: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Detailed Clinical History Collections (JSON structured arrays)
    # e.g., [{"condition": "Type 2 Diabetes", "diagnosed_year": 2019, "status": "ACTIVE", "notes": "Managed with Metformin"}]
    chronic_conditions: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    # e.g., [{"allergen": "Penicillin", "type": "DRUG", "severity": "SEVERE", "reaction": "Anaphylaxis"}]
    known_allergies: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    # e.g., [{"procedure": "Coronary Stent Placement", "year": 2021, "hospital": "Heart Institute", "notes": "DES in LAD"}]
    past_surgeries: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    # e.g., [{"medicine_name": "Atorvastatin 20mg", "dosage": "1 tab nightly", "prescribed_for": "Dyslipidemia"}]
    ongoing_medications: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    # e.g., [{"relation": "Father", "condition": "Hypertension & Stroke at age 55"}]
    family_medical_history: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    # Lifestyle & Social Factors
    # e.g., {"smoking_status": "NEVER", "alcohol_use": "NONE", "dietary_restrictions": "LOW_SODIUM"}
    lifestyle_factors: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # Emergency Contact Details
    emergency_contact_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    emergency_contact_phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    emergency_contact_relation: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Clinical Free-text Notes & Special Considerations
    clinical_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    patient: Mapped["User"] = relationship("User", lazy="joined")

    def __repr__(self) -> str:
        return f"<PatientMedicalProfile patient_id={self.patient_id} blood_group={self.blood_group}>"


class PatientVitalsLog(Base, TimestampMixin):
    """
    Vital signs log entry with AI-powered MEWS / NEWS acuity scoring
    and automated critical alert dispatch to patient's consultant doctor.
    """
    __tablename__ = "patient_vitals_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=generate_uuid
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    recorded_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    # Source: "PATIENT_SELF_REPORT" or "COMPOUNDER_INTAKE"
    source: Mapped[str] = mapped_column(String(30), default="PATIENT_SELF_REPORT", index=True, nullable=False)
    appointment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("appointments.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Primary Physiological Vital Signs
    systolic_bp: Mapped[int] = mapped_column(Integer, nullable=False)  # mmHg
    diastolic_bp: Mapped[int] = mapped_column(Integer, nullable=False)  # mmHg
    heart_rate: Mapped[int] = mapped_column(Integer, nullable=False)  # bpm
    respiratory_rate: Mapped[int] = mapped_column(Integer, default=16, nullable=False)  # breaths/min
    temperature_f: Mapped[float] = mapped_column(Float, default=98.6, nullable=False)  # °F
    spo2: Mapped[float] = mapped_column(Float, default=98.0, nullable=False)  # Oxygen saturation %
    blood_glucose: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # mg/dL
    consciousness_level: Mapped[str] = mapped_column(String(20), default="ALERT", nullable=False)  # ALERT, VOICE, PAIN, UNRESPONSIVE
    symptoms_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Early Warning & Triage Acuity Scores
    mews_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # Modified Early Warning Score
    news2_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # National Early Warning Score
    triage_level: Mapped[str] = mapped_column(
        String(30), default="NORMAL", index=True, nullable=False
    )  # NORMAL, LOW_RISK, MODERATE_RISK, CRITICAL_EMERGENCY
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)

    # AI Medical History Context Analysis
    ai_analysis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    clinical_recommendation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risk_factors_detected: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)

    # Doctor Escalation & Notification
    notified_doctor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("doctor_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    doctor_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    doctor_alert_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    doctor_acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    patient: Mapped["User"] = relationship("User", foreign_keys=[patient_id], lazy="joined")
    recorded_by: Mapped["User"] = relationship("User", foreign_keys=[recorded_by_id], lazy="joined")
    appointment: Mapped[Optional["Appointment"]] = relationship("Appointment", lazy="joined")
    notified_doctor: Mapped[Optional["DoctorProfile"]] = relationship("DoctorProfile", lazy="joined")

    def __repr__(self) -> str:
        return f"<PatientVitalsLog patient_id={self.patient_id} mews={self.mews_score} critical={self.is_critical}>"
