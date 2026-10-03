from datetime import datetime
import uuid
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from app.schemas.role import RoleResponse

class UserBase(BaseModel):
    email: EmailStr
    phone: Optional[str] = Field(None, json_schema_extra={"example": "+1234567890"})
    full_name: str = Field(..., json_schema_extra={"example": "Dr. Jane Doe"})

class UserCreate(UserBase):
    password: str = Field(..., min_length=6, description="User password")

class UserStaffCreate(UserCreate):
    role_codes: List[str] = Field(..., min_length=1, description="List of role codes to assign to staff member (e.g. ['DOCTOR'])")

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None
    is_verified: Optional[bool] = None

class UserAssignRoles(BaseModel):
    role_codes: List[str] = Field(..., description="Complete list of role codes to associate with the user")

class UserResponse(UserBase):
    id: uuid.UUID
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class UserWithRolesResponse(UserResponse):
    roles: List[RoleResponse] = []
    permissions: List[str] = []

    model_config = ConfigDict(from_attributes=True)
