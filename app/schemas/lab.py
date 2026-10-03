from datetime import datetime
import uuid
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.doctor import DoctorProfileResponse
from app.schemas.user import UserResponse

class LabTestCatalogBase(BaseModel):
    name: str = Field(..., description="Test name", json_schema_extra={"example": "Complete Blood Count (CBC)"})
    code: str = Field(..., description="Unique test code", json_schema_extra={"example": "CBC"})
    category: str = Field(..., description="Clinical test category", json_schema_extra={"example": "HEMATOLOGY"})
    description: Optional[str] = None
    standard_turnaround_hours: int = Field(default=24, ge=1)
    is_active: bool = True

class LabTestCatalogCreate(LabTestCatalogBase):
    pass

class LabTestCatalogResponse(LabTestCatalogBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class LabOrderCreate(BaseModel):
    test_id: uuid.UUID = Field(..., description="Lab test catalog ID")
    instructions: Optional[str] = Field(None, description="Special instructions e.g. 10hr fasting")
    urgency: str = Field("ROUTINE", description="ROUTINE, URGENT, STAT")

class LabResultSubmitRequest(BaseModel):
    result_summary: str = Field(..., min_length=2, description="Clinical summary of test findings", json_schema_extra={"example": "Hemoglobin: 14.1 g/dL, WBC: 7,200 /uL, Platelets: 220,000 /uL. Normal limits."})
    findings_json: Optional[Dict[str, Any]] = Field(None, description="Key-value dictionary of numeric parameters and units")
    report_file_url: Optional[str] = Field(None, description="URL or path to uploaded PDF report")
    is_abnormal: bool = Field(default=False, description="Flag if any parameter falls in abnormal range")
    critical_alert: Optional[str] = Field(None, description="Critical danger alert flag e.g. 'Critically low platelets'")

class LabResultResponse(BaseModel):
    id: uuid.UUID
    lab_order_id: uuid.UUID
    lab_assistant_id: uuid.UUID
    result_summary: str
    findings_json: Optional[Dict[str, Any]] = None
    report_file_url: Optional[str] = None
    is_abnormal: bool
    critical_alert: Optional[str] = None
    completed_at: datetime
    lab_assistant: Optional[UserResponse] = None

    model_config = ConfigDict(from_attributes=True)

class LabOrderResponse(BaseModel):
    id: uuid.UUID
    consultation_id: uuid.UUID
    test_id: uuid.UUID
    patient_id: uuid.UUID
    doctor_id: uuid.UUID
    instructions: Optional[str] = None
    urgency: str
    status: str
    sample_collected_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    test: Optional[LabTestCatalogResponse] = None
    patient: Optional[UserResponse] = None
    doctor: Optional[DoctorProfileResponse] = None
    result: Optional[LabResultResponse] = None

    model_config = ConfigDict(from_attributes=True)
