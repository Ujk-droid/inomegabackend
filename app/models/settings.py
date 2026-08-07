from datetime import datetime

from pydantic import BaseModel, Field


class SettingsOut(BaseModel):
    human_gate_threshold: float | None = None  # None for Staff's reduced view (Section 3.2)
    updated_at: datetime | None = None


class SettingsUpdate(BaseModel):
    human_gate_threshold: float = Field(..., gt=0)
