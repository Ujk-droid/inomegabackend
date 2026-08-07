from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.ledger import LineItemCreate, LineItemOut


class PurchaseCreate(BaseModel):
    party_id: str
    line_items: list[LineItemCreate] = Field(..., min_length=1)
    discount_amount: float = Field(default=0.0, ge=0)
    transaction_date: date
    received_amount: float = Field(default=0.0, ge=0)


class PurchaseOut(BaseModel):
    id: str
    purchase_bill_no: str | None = None
    party_id: str
    transaction_date: date
    discount_amount: float
    total_amount: float
    received_amount: float
    previous_balance: float
    current_balance: float
    line_items: list[LineItemOut]
    created_at: datetime | None = None
