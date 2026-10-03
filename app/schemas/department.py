from datetime import datetime
import uuid
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

class DepartmentBase(BaseModel):
    name: str = Field(..., description="Department name", json_schema_extra={"example": "Cardiology"})
    code: str = Field(..., description="Unique department code", json_schema_extra={"example": "CARDIOLOGY"})
    description: Optional[str] = Field(None, description="Department description")
    is_active: bool = True

class DepartmentCreate(DepartmentBase):
    pass

class DepartmentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

class DepartmentResponse(DepartmentBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
