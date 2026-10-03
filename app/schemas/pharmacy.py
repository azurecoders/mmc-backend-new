from datetime import datetime
import uuid
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.consultation import PrescriptionItemResponse
from app.schemas.user import UserResponse

class PharmacyMedicineBase(BaseModel):
    name: str = Field(..., description="Trade name & strength", json_schema_extra={"example": "Atorvastatin 20mg"})
    generic_name: str = Field(..., description="Active pharmaceutical ingredient", json_schema_extra={"example": "Atorvastatin Calcium"})
    category: str = Field(..., description="Pharmacological class", json_schema_extra={"example": "CARDIOVASCULAR"})
    dosage_form: str = Field(..., description="TABLET, CAPSULE, SYRUP, INJECTION", json_schema_extra={"example": "TABLET"})
    unit_price: float = Field(default=1.50, ge=0.0)
    stock_quantity: int = Field(default=100, ge=0)
    reorder_level: int = Field(default=20, ge=0)
    is_active: bool = True

class PharmacyMedicineCreate(PharmacyMedicineBase):
    pass

class PharmacyMedicineUpdate(BaseModel):
    name: Optional[str] = None
    generic_name: Optional[str] = None
    category: Optional[str] = None
    dosage_form: Optional[str] = None
    unit_price: Optional[float] = None
    stock_quantity: Optional[int] = None
    reorder_level: Optional[int] = None
    is_active: Optional[bool] = None

class PharmacyMedicineResponse(PharmacyMedicineBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class DispenseItemRequest(BaseModel):
    prescription_item_id: uuid.UUID
    status: str = Field("DISPENSED", description="DISPENSED, OUT_OF_STOCK, SUBSTITUTED")
    notes: Optional[str] = Field(None, description="e.g. Substituted with Brand Y (same 20mg salt)")
    deduct_inventory: bool = Field(default=True, description="Automatically decrement medicine stock if found in inventory")
    quantity_deducted: Optional[int] = Field(default=1, ge=1, description="Quantity of units/tablets to decrement from stock")

class PrescriptionDispenseBatchRequest(BaseModel):
    consultation_id: uuid.UUID
    items: List[DispenseItemRequest]
    counter_name: Optional[str] = Field("Pharmacy Counter #1", description="Collection counter for patient")

class MedicineDispenseRecordResponse(BaseModel):
    id: uuid.UUID
    prescription_item_id: uuid.UUID
    pharmacist_id: uuid.UUID
    status: str
    notes: Optional[str] = None
    dispensed_at: datetime
    pharmacist: Optional[UserResponse] = None

    model_config = ConfigDict(from_attributes=True)

class PharmacyPrescriptionQueueItem(BaseModel):
    consultation_id: uuid.UUID
    appointment_id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str
    patient_phone: Optional[str] = None
    doctor_name: str
    room_number: str
    diagnosis: str
    prescribed_at: datetime
    is_all_dispensed: bool
    items: List[PrescriptionItemResponse] = []
