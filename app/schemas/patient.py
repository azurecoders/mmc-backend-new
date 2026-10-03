from datetime import date, datetime
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.user import UserResponse

# --- Detailed Medical History Structured Schemas ---

class ChronicConditionItem(BaseModel):
    condition: str = Field(..., description="e.g. Type 2 Diabetes, Hypertension, Asthma")
    diagnosed_year: Optional[int] = Field(None, description="Year of diagnosis e.g. 2019")
    status: str = Field("ACTIVE", description="ACTIVE, RESOLVED, IN_REMISSION")
    notes: Optional[str] = Field(None, description="Treatment notes or physician remarks")

class AllergyItem(BaseModel):
    allergen: str = Field(..., description="Allergen name e.g. Penicillin, Sulfa drugs, Peanuts")
    type: str = Field("DRUG", description="DRUG, FOOD, ENVIRONMENTAL, LATEX")
    severity: str = Field("MODERATE", description="MILD, MODERATE, SEVERE, ANAPHYLAXIS")
    reaction: Optional[str] = Field(None, description="e.g. Hives, Dyspnea, Facial swelling")

class PastSurgeryItem(BaseModel):
    procedure: str = Field(..., description="Surgical procedure name e.g. Cholecystectomy")
    year: Optional[int] = Field(None, description="Year surgery performed")
    hospital: Optional[str] = Field(None, description="Hospital or clinic name")
    notes: Optional[str] = Field(None, description="Implants, stents, or complications")

class OngoingMedicationItem(BaseModel):
    medicine_name: str = Field(..., description="e.g. Metformin 500mg, Lisinopril 10mg")
    dosage: str = Field(..., description="e.g. 1 tab twice daily")
    prescribed_for: Optional[str] = Field(None, description="e.g. Glycemic control")

class FamilyHistoryItem(BaseModel):
    relation: str = Field(..., description="e.g. Father, Mother, Sibling")
    condition: str = Field(..., description="e.g. Myocardial Infarction at age 50, Colon Cancer")

class LifestyleFactors(BaseModel):
    smoking_status: Optional[str] = Field("NEVER", description="NEVER, CURRENT, FORMER")
    alcohol_use: Optional[str] = Field("NONE", description="NONE, OCCASIONAL, MODERATE, HEAVY")
    exercise_level: Optional[str] = Field("MODERATE", description="SEDENTARY, LIGHT, MODERATE, ATHLETIC")
    dietary_restrictions: Optional[str] = Field(None, description="e.g. Low sodium, Diabetic diet, Renal diet")

# --- Patient Medical Profile Requests / Responses ---

class PatientMedicalProfileBase(BaseModel):
    blood_group: Optional[str] = Field(None, description="e.g. O+, A+, B+, AB-")
    date_of_birth: Optional[date] = None
    gender: Optional[str] = Field(None, description="MALE, FEMALE, OTHER")
    height_cm: Optional[float] = Field(None, ge=30.0, le=280.0)
    weight_kg: Optional[float] = Field(None, ge=1.0, le=500.0)
    baseline_systolic_bp: Optional[int] = Field(None, ge=50, le=260)
    baseline_diastolic_bp: Optional[int] = Field(None, ge=30, le=160)
    chronic_conditions: List[ChronicConditionItem] = []
    known_allergies: List[AllergyItem] = []
    past_surgeries: List[PastSurgeryItem] = []
    ongoing_medications: List[OngoingMedicationItem] = []
    family_medical_history: List[FamilyHistoryItem] = []
    lifestyle_factors: Optional[LifestyleFactors] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relation: Optional[str] = None
    clinical_notes: Optional[str] = None

class PatientMedicalProfileUpdate(PatientMedicalProfileBase):
    pass

class PatientMedicalProfileResponse(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    blood_group: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    baseline_systolic_bp: Optional[int] = None
    baseline_diastolic_bp: Optional[int] = None
    chronic_conditions: List[Dict[str, Any]] = []
    known_allergies: List[Dict[str, Any]] = []
    past_surgeries: List[Dict[str, Any]] = []
    ongoing_medications: List[Dict[str, Any]] = []
    family_medical_history: List[Dict[str, Any]] = []
    lifestyle_factors: Dict[str, Any] = {}
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relation: Optional[str] = None
    clinical_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Vitals Logging & AI Triage Scoring Schemas ---

class VitalsInputBase(BaseModel):
    systolic_bp: int = Field(..., ge=50, le=280, description="Systolic Blood Pressure (mmHg)")
    diastolic_bp: int = Field(..., ge=30, le=180, description="Diastolic Blood Pressure (mmHg)")
    heart_rate: int = Field(..., ge=25, le=250, description="Heart Rate (beats/minute)")
    respiratory_rate: int = Field(default=16, ge=4, le=60, description="Respiratory Rate (breaths/minute)")
    temperature_f: float = Field(default=98.6, ge=90.0, le=108.0, description="Body Temperature (°F)")
    spo2: float = Field(default=98.0, ge=50.0, le=100.0, description="Oxygen Saturation (% SpO2)")
    blood_glucose: Optional[float] = Field(None, ge=10.0, le=800.0, description="Capillary blood glucose (mg/dL)")
    consciousness_level: str = Field(default="ALERT", description="AVPU: ALERT, VOICE, PAIN, UNRESPONSIVE")
    symptoms_notes: Optional[str] = Field(None, description="Current symptoms or complaints e.g. dizziness, crushing chest pressure")

class PatientSelfVitalsLogCreate(VitalsInputBase):
    """Submitted by patient from their self-care portal."""
    pass

class CompounderVitalsIntakeCreate(VitalsInputBase):
    """Submitted by compounder during patient check-in / triage."""
    appointment_id: uuid.UUID
    is_priority_override: Optional[bool] = Field(
        None, description="Optional manual override to escalate token to priority in queue"
    )

class PatientVitalsLogResponse(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    recorded_by_id: uuid.UUID
    source: str
    appointment_id: Optional[uuid.UUID] = None
    systolic_bp: int
    diastolic_bp: int
    heart_rate: int
    respiratory_rate: int
    temperature_f: float
    spo2: float
    blood_glucose: Optional[float] = None
    consciousness_level: str
    symptoms_notes: Optional[str] = None

    # Triage & AI Acuity Evaluation
    mews_score: int
    news2_score: int
    triage_level: str
    is_critical: bool
    ai_analysis: Optional[str] = None
    clinical_recommendation: Optional[str] = None
    risk_factors_detected: List[str] = []

    # Escalation details
    notified_doctor_id: Optional[uuid.UUID] = None
    doctor_notified_at: Optional[datetime] = None
    doctor_alert_acknowledged: bool = False
    doctor_name: Optional[str] = None

    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DoctorCriticalAlertItem(BaseModel):
    vitals_log_id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str
    patient_phone: Optional[str] = None
    appointment_id: Optional[uuid.UUID] = None
    triage_level: str
    is_critical: bool
    mews_score: int
    systolic_bp: int
    diastolic_bp: int
    heart_rate: int
    spo2: float
    temperature_f: float
    symptoms_notes: Optional[str] = None
    ai_analysis: Optional[str] = None
    clinical_recommendation: Optional[str] = None
    risk_factors_detected: List[str] = []
    recorded_at: datetime
    acknowledged: bool

    model_config = ConfigDict(from_attributes=True)
