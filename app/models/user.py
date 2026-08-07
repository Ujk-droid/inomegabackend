from datetime import datetime

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    email: str
    role: str = Field(default="staff")  # 'admin' | 'staff'


class UserOut(BaseModel):
    id: str
    full_name: str
    email: str
    role: str
    is_active: bool
    last_login: datetime | None = None
    created_at: datetime | None = None
