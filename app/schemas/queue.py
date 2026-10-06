from datetime import date, datetime
import uuid
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.appointment import AppointmentResponse
from app.schemas.doctor import DoctorProfileResponse
from app.schemas.user import UserResponse

class QueueEntryResponse(BaseModel):
    id: uuid.UUID
    appointment_id: uuid.UUID
    doctor_id: uuid.UUID
    patient_id: uuid.UUID
    queue_date: date
    token_number: int
    status: str
    is_priority: bool
    check_in_time: datetime
    called_in_time: Optional[datetime] = None
    session_start_time: Optional[datetime] = None
    session_end_time: Optional[datetime] = None
    called_by_user_id: Optional[uuid.UUID] = None

    patient: Optional[UserResponse] = None
    doctor: Optional[DoctorProfileResponse] = None
    appointment: Optional[AppointmentResponse] = None

    model_config = ConfigDict(from_attributes=True)

class PatientLiveQueueStatus(BaseModel):
    appointment_id: uuid.UUID
    queue_entry_id: uuid.UUID
    your_token_number: int
    status: str
    is_your_turn: bool
    currently_serving_token: Optional[int] = None
    patients_ahead: int = 0
    estimated_wait_time_minutes: int = 0
    is_priority: bool = False
    doctor_name: str
    doctor_specialization: str
    room_number: str
    queue_date: date

class DoctorLiveQueueSummary(BaseModel):
    doctor_id: uuid.UUID
    doctor_name: str
    specialization: str
    room_number: str
    active_token: Optional[int] = None
    active_token_status: Optional[str] = None
    active_patient_name: Optional[str] = None
    total_waiting: int = 0
    total_completed_today: int = 0
    upcoming_tokens: List[int] = []

class WaitingRoomTVDisplay(BaseModel):
    hospital_name: str
    queue_date: date
    doctors: List[DoctorLiveQueueSummary] = []

class QueueCheckInRequest(BaseModel):
    appointment_id: uuid.UUID = Field(..., description="Approved appointment ID to check into queue")
    is_priority: bool = Field(default=False, description="Set True for emergency or priority patient")

class QueueCallPatientRequest(BaseModel):
    queue_entry_id: Optional[uuid.UUID] = Field(None, description="Queue entry to activate/call into doctor cabin")
    doctor_id: Optional[uuid.UUID] = Field(None, description="Doctor ID to call the next waiting patient for")

