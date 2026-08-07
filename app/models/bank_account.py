from pydantic import BaseModel, Field


class BankAccountCreate(BaseModel):
    bank_name: str = Field(..., min_length=1, max_length=100)
    account_note: str | None = None


class BankAccountUpdate(BaseModel):
    account_note: str | None = None
    is_active: bool | None = None


class BankAccountOut(BaseModel):
    id: str
    bank_name: str
    account_note: str | None = None
    is_active: bool
