from datetime import date, datetime
import uuid
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from app.schemas.doctor import DoctorProfileResponse
from app.schemas.user import UserResponse

class WalkinPatientCreate(BaseModel):
    full_name: str = Field(..., description="Patient full name", json_schema_extra={"example": "John Walkin"})
    phone: Optional[str] = Field(None, description="Patient contact phone", json_schema_extra={"example": "+19988776655"})
    email: Optional[EmailStr] = Field(None, description="Patient email address")

class AIRecommendDoctorsRequest(BaseModel):
    symptoms: str = Field(..., min_length=3, description="Describe symptoms or reasons for visit", json_schema_extra={"example": "Persistent chest heaviness and shortness of breath when walking up stairs for 4 days"})
    duration: Optional[str] = Field(None, description="Duration of symptoms", json_schema_extra={"example": "4 days"})
    severity: Optional[str] = Field("MODERATE", description="Self-reported severity: MILD, MODERATE, SEVERE")
    preferred_date: Optional[date] = None

class DoctorRecommendationItem(BaseModel):
    doctor: DoctorProfileResponse
    match_score: float = Field(..., description="Match confidence score between 0.0 and 1.0")
    match_reason: str = Field(..., description="Why this specialist is recommended for the symptoms")

class AIRecommendDoctorsResponse(BaseModel):
    recommended_department: str = Field(..., description="Name or code of the most appropriate clinical department")
    urgency_level: str = Field(..., description="ROUTINE, URGENT, or EMERGENCY")
    clinical_assessment: str = Field(..., description="AI triage summary of the symptoms")
    recommended_doctors: List[DoctorRecommendationItem] = []
    fallback_used: bool = False

class AppointmentOnlineBooking(BaseModel):
    doctor_id: uuid.UUID = Field(..., description="Selected doctor profile ID")
    appointment_date: date = Field(..., description="Requested consultation date")
    slot_time: str = Field(..., description="Time slot in HH:MM format", json_schema_extra={"example": "10:30"})
    chief_complaint: str = Field(..., min_length=3, description="Patient's primary complaint")
    symptom_duration: Optional[str] = None
    severity: Optional[str] = "MODERATE"
    ai_recommended_department: Optional[str] = None
    ai_recommendation_reason: Optional[str] = None

class AppointmentWalkinBooking(BaseModel):
    # Either existing patient_id or walkin_patient details
    patient_id: Optional[uuid.UUID] = None
    walkin_patient: Optional[WalkinPatientCreate] = None
    
    doctor_id: uuid.UUID = Field(..., description="Selected doctor profile ID")
    appointment_date: Optional[date] = None  # defaults to today
    slot_time: Optional[str] = None  # defaults to current time
    chief_complaint: str = Field(..., min_length=2, description="Walk-in symptoms/complaints recorded by compounder")
    symptom_duration: Optional[str] = None
    severity: Optional[str] = "MODERATE"

class AppointmentApproveRequest(BaseModel):
    notes: Optional[str] = Field(None, description="Optional verification notes by compounder")

class AppointmentRejectRequest(BaseModel):
    rejection_reason: str = Field(..., min_length=3, description="Reason for rejecting the appointment")

class AppointmentResponse(BaseModel):
    id: uuid.UUID
    appointment_number: str
    patient_id: uuid.UUID
    doctor_id: uuid.UUID
    booking_type: str
    appointment_date: date
    slot_time: str
    token_number: int
    chief_complaint: str
    symptom_duration: Optional[str] = None
    severity: Optional[str] = None
    ai_recommended_department: Optional[str] = None
    ai_recommendation_reason: Optional[str] = None
    status: str
    verified_by_compounder_id: Optional[uuid.UUID] = None
    verified_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    patient: Optional[UserResponse] = None
    doctor: Optional[DoctorProfileResponse] = None
    verified_by_compounder: Optional[UserResponse] = None

    model_config = ConfigDict(from_attributes=True)
