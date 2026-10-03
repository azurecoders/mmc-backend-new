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
