from datetime import datetime
import uuid
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict

class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    phone: Optional[str] = None
    role_names: List[str] = []

class EmergencyCodeGroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    color_hex: str
    badge_color: str
    description: str
    call_to_action: str
    is_active: bool
    members: List[UserBrief] = []
    member_count: int = 0

class EmergencyGroupMemberAddRequest(BaseModel):
    user_id: uuid.UUID

class EmergencyTriggerRequest(BaseModel):
    code: str = Field(..., description="e.g. CODE_BLUE, CODE_RED, RAPID_RESPONSE")
    ward: str = Field(..., description="e.g. ICU - Intensive Care Unit, Floor 2 Ward B")
    location_details: Optional[str] = Field(None, description="e.g. Bed 4, Room 204")
    notes: Optional[str] = Field(None, description="e.g. Adult male, pulseless, CPR initiated")

class EmergencyResponderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    user_name: str
    status: str
    responded_at: datetime
    note: Optional[str] = None

class EmergencyAlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    code_name: str
    color_hex: str
    ward: str
    location_details: Optional[str] = None
    notes: Optional[str] = None
    status: str  # ACTIVE, ACKNOWLEDGED, RESOLVED, CANCELLED
    triggered_at: datetime
    triggered_by_id: uuid.UUID
    triggered_by_name: str
    resolved_at: Optional[datetime] = None
    resolved_by_id: Optional[uuid.UUID] = None
    resolved_by_name: Optional[str] = None
    resolution_notes: Optional[str] = None
    assigned_members_count: int = 0
    responders_count: int = 0
    responders: List[EmergencyResponderResponse] = []

class EmergencyAcknowledgeRequest(BaseModel):
    note: Optional[str] = None

class EmergencyResolveRequest(BaseModel):
    resolution_notes: Optional[str] = Field(None, description="Details of patient stabilization, fire extinguished, etc.")
