from datetime import datetime

from pydantic import BaseModel, Field


class LoginCreate(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    status: str  # 'authenticated' | 'pending'
    role: str | None = None
    request_id: str | None = None


class ForgotPasswordCreate(BaseModel):
    email: str


class ResetPasswordCreate(BaseModel):
    new_password: str = Field(..., min_length=8)


class LoginRequestOut(BaseModel):
    id: str
    user_id: str
    status: str  # 'pending' | 'approved' | 'rejected' | 'expired'
    requested_at: datetime | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    ip_address: str | None = None
    note: str | None = None


class LoginRequestNote(BaseModel):
    note: str = Field(..., min_length=1)
