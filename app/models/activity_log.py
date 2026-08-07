from datetime import datetime

from pydantic import BaseModel


class ActivityLogOut(BaseModel):
    id: str
    user_id: str
    user_name: str | None = None
    action: str
    target_description: str
    created_at: datetime | None = None
