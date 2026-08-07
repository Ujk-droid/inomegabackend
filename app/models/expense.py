from datetime import date, datetime

from pydantic import BaseModel, Field


class ExpenseCreate(BaseModel):
    expense_date: date
    party_id: str | None = None
    description: str | None = None
    amount: float = Field(..., gt=0)
    particular: str | None = Field(default=None, description="Name from the particulars master table")


class ExpenseOut(BaseModel):
    id: str
    serial_number: int | None = None
    expense_date: date
    party_id: str | None = None
    description: str | None = None
    amount: float
    particular_id: str | None = None
    particular_name: str | None = None
    created_at: datetime | None = None
