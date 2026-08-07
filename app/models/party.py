from datetime import datetime

from pydantic import BaseModel, Field


class PartyCreate(BaseModel):
    party_name: str = Field(..., min_length=1, max_length=255)
    party_type: str = Field(default="customer")  # 'customer' | 'supplier' | 'both'
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    credit_limit: float | None = None


class PartyOut(BaseModel):
    id: str
    party_name: str
    party_type: str
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    credit_limit: float | None = None
    created_at: datetime | None = None


class PartyBalanceOut(BaseModel):
    party_id: str
    current_balance: float
    credit_limit: float | None = None
    lifetime_business: float = 0.0


class NegotiatedRateCreate(BaseModel):
    item_code: str
    negotiated_rate: float = Field(..., gt=0)


class NegotiatedRateOut(BaseModel):
    party_id: str
    item_code: str
    negotiated_rate: float | None = None  # null when this party has no negotiated rate for this item
