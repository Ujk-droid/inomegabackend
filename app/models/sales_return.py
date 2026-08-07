from datetime import datetime

from pydantic import BaseModel, Field


class SalesReturnCreate(BaseModel):
    item_code: str
    qty_returned: int = Field(..., gt=0)
    reason: str | None = None


class SalesReturnOut(BaseModel):
    id: str
    original_invoice_id: str
    item_code: str
    qty_returned: int
    reason: str | None = None
    ledger_credit_id: str | None = None
    processed_by: str
    created_at: datetime | None = None
