from datetime import datetime
import uuid
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.department import DepartmentResponse
from app.schemas.user import UserResponse

class DoctorScheduleBase(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6, description="0=Monday, 6=Sunday")
    start_time: str = Field(..., description="Schedule start time in HH:MM format", json_schema_extra={"example": "09:00"})
    end_time: str = Field(..., description="Schedule end time in HH:MM format", json_schema_extra={"example": "17:00"})
    max_daily_patients: int = Field(default=30, ge=1, le=100)
    is_active: bool = True

class DoctorScheduleCreate(DoctorScheduleBase):
    pass

class DoctorScheduleResponse(DoctorScheduleBase):
    id: uuid.UUID
    doctor_id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)

class DoctorProfileBase(BaseModel):
    specialization: str = Field(..., description="Clinical specialization", json_schema_extra={"example": "Interventional Cardiologist"})
    qualifications: str = Field(..., description="Medical degrees & certifications", json_schema_extra={"example": "MBBS, MD (Cardiology), FACC"})
    experience_years: int = Field(default=0, ge=0)
    consultation_fee: float = Field(default=50.0, ge=0.0)
    room_number: str = Field(..., description="Clinic cabin or room number", json_schema_extra={"example": "Cabin 302, 3rd Floor"})
    bio: Optional[str] = None
    is_available: bool = True
    avg_consultation_mins: int = Field(default=15, ge=5, le=60)

class DoctorProfileCreate(DoctorProfileBase):
    user_id: uuid.UUID
    department_id: uuid.UUID
    schedules: Optional[List[DoctorScheduleCreate]] = None

class DoctorProfileUpdate(BaseModel):
    specialization: Optional[str] = None
    qualifications: Optional[str] = None
    experience_years: Optional[int] = None
    consultation_fee: Optional[float] = None
    room_number: Optional[str] = None
    bio: Optional[str] = None
    is_available: Optional[bool] = None
    avg_consultation_mins: Optional[int] = None
    department_id: Optional[uuid.UUID] = None

class DoctorProfileResponse(DoctorProfileBase):
    id: uuid.UUID
    user_id: uuid.UUID
    department_id: uuid.UUID
    user: Optional[UserResponse] = None
    department: Optional[DepartmentResponse] = None
    schedules: List[DoctorScheduleResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
