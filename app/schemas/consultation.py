from datetime import date, datetime
import uuid
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.schemas.appointment import AppointmentResponse
from app.schemas.doctor import DoctorProfileResponse
from app.schemas.lab import LabOrderCreate, LabOrderResponse
from app.schemas.user import UserResponse

class PrescriptionItemCreate(BaseModel):
    medicine_name: str = Field(..., description="Medicine name with salt/strength", json_schema_extra={"example": "Amoxicillin 500mg"})
    dosage: str = Field(default="1 dose", description="Dosage quantity", json_schema_extra={"example": "1 capsule"})
    frequency: str = Field(default="Once daily", description="Dosage schedule", json_schema_extra={"example": "1-0-1 (Morning & Night)"})
    duration: str = Field(default="5 days", description="Course duration", json_schema_extra={"example": "5 days"})
    instructions: Optional[str] = Field(None, description="Special instructions", json_schema_extra={"example": "After meals with water"})

class PrescriptionItemResponse(BaseModel):
    id: uuid.UUID
    consultation_id: uuid.UUID
    medicine_name: str
    dosage: str
    frequency: str
    duration: str
    instructions: Optional[str] = None
    dispense_status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ConsultationCreate(BaseModel):
    appointment_id: uuid.UUID = Field(..., description="Associated appointment ID")
    chief_complaint: Optional[str] = Field("General Consultation", description="Patient chief complaint")
    symptoms: Optional[str] = Field(None, description="Detailed reported symptoms")
    diagnosis: str = Field(..., min_length=2, description="Provisional or confirmed diagnosis", json_schema_extra={"example": "Acute Bacterial Bronchitis"})
    clinical_notes: Optional[str] = Field("Clinical examination and consultation completed.", description="Doctor clinical observations & examination notes")
    special_instructions: Optional[str] = Field(None, description="Dietary, hydration, or activity instructions")
    highlights: Optional[str] = Field(None, description="Critical warning flags or red flag symptoms")
    follow_up_date: Optional[date] = None
    
    # Prescriptions and Lab Orders in same consultation submission
    prescriptions: List[PrescriptionItemCreate] = []
    prescription_items: Optional[List[PrescriptionItemCreate]] = None
    lab_orders: List[LabOrderCreate] = []
    
    finalize: bool = Field(default=True, description="If True, completes visit and notifies patient/pharma/lab immediately")

    @model_validator(mode="before")
    @classmethod
    def reconcile_prescriptions(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # If prescription_items is supplied but prescriptions is empty, copy over
            items = data.get("prescriptions") or data.get("prescription_items") or []
            data["prescriptions"] = items
            data["prescription_items"] = items

            # Ensure chief_complaint and clinical_notes have valid non-empty content
            cc = data.get("chief_complaint")
            if not cc or not str(cc).strip():
                data["chief_complaint"] = "General Consultation"

            cn = data.get("clinical_notes")
            if not cn or not str(cn).strip():
                data["clinical_notes"] = "Clinical examination and evaluation completed."
        return data

class ConsultationUpdate(BaseModel):
    chief_complaint: Optional[str] = None
    symptoms: Optional[str] = None
    diagnosis: Optional[str] = None
    clinical_notes: Optional[str] = None
    special_instructions: Optional[str] = None
    highlights: Optional[str] = None
    follow_up_date: Optional[date] = None
    is_finalized: Optional[bool] = None

class ConsultationResponse(BaseModel):
    id: uuid.UUID
    appointment_id: uuid.UUID
    doctor_id: uuid.UUID
    patient_id: uuid.UUID
    chief_complaint: str
    symptoms: Optional[str] = None
    diagnosis: str
    clinical_notes: str
    special_instructions: Optional[str] = None
    highlights: Optional[str] = None
    follow_up_date: Optional[date] = None
    is_finalized: bool
    finalized_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    prescription_items: List[PrescriptionItemResponse] = []
    lab_orders: List[LabOrderResponse] = []
    doctor: Optional[DoctorProfileResponse] = None
    patient: Optional[UserResponse] = None
    appointment: Optional[AppointmentResponse] = None

    model_config = ConfigDict(from_attributes=True)

class MedicineExplanationItem(BaseModel):
    medicine_name: str
    purpose: str = Field(..., description="Plain-English medical purpose of this medicine")
    how_to_take: str = Field(..., description="Actionable timing and dosage instructions")
    precautions_and_side_effects: str = Field(..., description="Common side effects and precautions to be aware of")
    food_interaction: Optional[str] = Field(None, description="Food or drink interactions (e.g. take with water, avoid dairy)")

class PrescriptionExplanationResponse(BaseModel):
    consultation_id: uuid.UUID
    diagnosis: str
    doctor_name: str
    ai_model_used: str
    is_live_ai: bool
    summary: str = Field(..., description="Empathetic, clear patient overview of what this treatment plan does")
    medicines: List[MedicineExplanationItem] = []
    lifestyle_and_diet_recommendations: List[str] = []
    warning_signs_to_watch: List[str] = []
    general_advice: str
    created_at: datetime

# --- AI Feature 1: Drug Interaction & Allergy Safety Guard ---
class DrugSafetyCheckItem(BaseModel):
    interaction_type: str = Field(..., description="DRUG_DRUG, DRUG_ALLERGY, or DRUG_DISEASE")
    severity: str = Field(..., description="HIGH, MEDIUM, or LOW")
    primary_item: str = Field(..., description="The prescribed medicine involved")
    interacting_with: str = Field(..., description="The other drug, allergen, or condition")
    clinical_effect: str = Field(..., description="What adverse event or risk could occur")
    clinical_recommendation: str = Field(..., description="Alternative recommendation or monitoring advice")

class DrugSafetyCheckRequest(BaseModel):
    medicines: List[str] = Field(..., description="List of prescribed medicine names")
    allergies: Optional[List[str]] = Field(default=[], description="List of known patient drug allergies")
    chronic_conditions: Optional[List[str]] = Field(default=[], description="List of patient chronic conditions")
    patient_age: Optional[int] = None
    patient_gender: Optional[str] = None

class DrugSafetyCheckResponse(BaseModel):
    overall_safety: str = Field(..., description="SAFE, MODERATE_WARNING, or CRITICAL_CONTRAINDICATION")
    safety_score: int = Field(..., description="0-100 safety index score")
    summary: str
    warnings_count: int
    interactions: List[DrugSafetyCheckItem] = []
    safer_alternatives: List[str] = []
    ai_model_used: str
    is_live_ai: bool

# --- AI Feature 2: Differential Diagnosis & Lab Test Assistant ---
class DifferentialDiagnosisItem(BaseModel):
    diagnosis: str
    likelihood: str = Field(..., description="HIGH, MODERATE, or LOW")
    clinical_rationale: str
    recommended_tests: List[str] = []

class SuggestedLabOrderItem(BaseModel):
    test_name: str
    test_id: Optional[str] = None
    urgency: str = Field(default="ROUTINE", description="ROUTINE, URGENT, or STAT")
    clinical_justification: str

class ClinicalCopilotRequest(BaseModel):
    chief_complaint: str
    symptoms: Optional[str] = None
    vitals_bp: Optional[str] = None
    vitals_heart_rate: Optional[int] = None
    vitals_spo2: Optional[float] = None
    vitals_temperature: Optional[float] = None
    chronic_conditions: Optional[List[str]] = []
    patient_age: Optional[int] = None
    patient_gender: Optional[str] = None

class ClinicalCopilotResponse(BaseModel):
    summary_assessment: str
    differential_diagnoses: List[DifferentialDiagnosisItem] = []
    suggested_lab_orders: List[SuggestedLabOrderItem] = []
    red_flag_warnings: List[str] = []
    recommended_physical_exams: List[str] = []
    ai_model_used: str
    is_live_ai: bool

# --- AI Feature 3: Ambient Voice-to-SOAP Clinical Scribe ---
class VoiceToSoapRequest(BaseModel):
    dictation_text: str = Field(..., min_length=3, description="Spoken or typed consultation dictation")
    chief_complaint: Optional[str] = None
    vitals_summary: Optional[str] = None
    patient_name: Optional[str] = None

class ExtractedPrescription(BaseModel):
    medicine_name: str
    dosage: str = "1 tab"
    frequency: str = "Twice daily (1-0-1)"
    duration: str = "5 days"
    instructions: str = "After meals with water"

class VoiceToSoapResponse(BaseModel):
    subjective: str
    objective: str
    assessment: str
    plan: str
    structured_soap_notes: str
    suggested_diagnosis: str
    suggested_special_instructions: Optional[str] = None
    extracted_prescriptions: List[ExtractedPrescription] = []
    suggested_follow_up_days: Optional[int] = None
    ai_model_used: str
    is_live_ai: bool

# --- AI Feature 4: Personalized Diet & Lifestyle Plan Generator ---
class DayMealPlanItem(BaseModel):
    day: str = Field(..., description="Day title (e.g. Day 1 (Monday))")
    theme: str = Field(..., description="Daily dietary focus or clinical theme")
    breakfast: str = Field(..., description="Breakfast meal recommendation and portion guidance")
    lunch: str = Field(..., description="Lunch meal recommendation and portion guidance")
    snack: str = Field(..., description="Nutrient-dense healthy snack")
    dinner: str = Field(..., description="Dinner meal recommendation, light and digestible")
    clinical_note: Optional[str] = Field(None, description="Why this meal plan aids the patient condition")

class FoodRestrictionItem(BaseModel):
    food_to_avoid: str = Field(..., description="Name of food, ingredient, or beverage")
    reason: str = Field(..., description="Clinical reason why it exacerbates the patient condition")
    healthy_substitute: str = Field(..., description="Recommended healthy culinary alternative")

class GenerateDietPlanRequest(BaseModel):
    diagnosis: Optional[str] = None
    chronic_conditions: Optional[List[str]] = []
    allergies: Optional[List[str]] = []
    dietary_preferences: Optional[str] = None
    patient_age: Optional[int] = None
    patient_gender: Optional[str] = None

class PersonalizedDietPlanResponse(BaseModel):
    consultation_id: Optional[uuid.UUID] = None
    diagnosis: str
    patient_name: str
    target_conditions: List[str] = []
    dietary_framework: str = Field(..., description="Clinical nutritional protocol name (e.g. DASH, Low-GI)")
    daily_calorie_target: Optional[str] = None
    daily_hydration_liters: float = Field(..., description="Recommended daily water/fluid intake in liters")
    hydration_guidelines: str = Field(..., description="Specific hydration schedule and advice")
    foods_to_avoid: List[FoodRestrictionItem] = []
    seven_day_meal_plan: List[DayMealPlanItem] = []
    physical_activity_plan: List[str] = []
    lifestyle_and_sleep_habits: List[str] = []
    clinical_precautions: List[str] = []
    ai_model_used: str
    is_live_ai: bool
    generated_at: datetime


