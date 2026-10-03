from datetime import datetime
import uuid
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

class PermissionBase(BaseModel):
    code: str = Field(..., description="Unique permission code (module:action)", json_schema_extra={"example": "appointments:create"})
    name: str = Field(..., description="Human-readable name", json_schema_extra={"example": "Create Appointment"})
    module: str = Field(..., description="Module or domain group", json_schema_extra={"example": "APPOINTMENTS"})
    description: Optional[str] = Field(None, description="Allows creating new patient appointments")

class PermissionCreate(PermissionBase):
    pass

class PermissionResponse(PermissionBase):
    id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
