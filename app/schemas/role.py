from datetime import datetime
import uuid
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.permission import PermissionResponse

class RoleBase(BaseModel):
    code: str = Field(..., description="Unique uppercase role code", json_schema_extra={"example": "DOCTOR"})
    name: str = Field(..., description="Display name for role", json_schema_extra={"example": "Doctor"})
    description: Optional[str] = Field(None, description="Role description")
    parent_role_id: Optional[uuid.UUID] = Field(None, description="Optional parent role ID for sub-roles (inherits parent permissions)")

class RoleCreate(RoleBase):
    permission_codes: Optional[List[str]] = Field(default=[], description="List of permission codes to attach to this role")

class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    parent_role_id: Optional[uuid.UUID] = None
    permission_codes: Optional[List[str]] = None

class RoleResponse(RoleBase):
    id: uuid.UUID
    is_system: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class RoleWithPermissionsResponse(RoleResponse):
    permissions: List[PermissionResponse] = []
    sub_roles: List[RoleResponse] = []
    effective_permission_codes: List[str] = []

    model_config = ConfigDict(from_attributes=True)
