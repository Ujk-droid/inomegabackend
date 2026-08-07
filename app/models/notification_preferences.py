from pydantic import BaseModel


class NotificationPreferencesOut(BaseModel):
    low_stock_digest: bool
    human_gate_approval: bool
    login_approval_request: bool


class NotificationPreferencesUpdate(BaseModel):
    low_stock_digest: bool | None = None
    human_gate_approval: bool | None = None
    login_approval_request: bool | None = None
