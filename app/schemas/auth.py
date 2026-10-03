from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field
from app.schemas.user import UserWithRolesResponse

class LoginRequest(BaseModel):
    username_or_email: str = Field(..., description="Email or phone number")
    password: str = Field(..., description="Account password")

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserWithRolesResponse

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6)

class MessageResponse(BaseModel):
    message: str
