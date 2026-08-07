from datetime import datetime

from pydantic import BaseModel, Field

VALID_REASONS = {"damaged", "lost", "count_correction", "other"}


class StockAdjustmentCreate(BaseModel):
    counted_qty: int = Field(..., ge=0)
    reason: str  # 'damaged' | 'lost' | 'count_correction' | 'other'
    note: str | None = None


class StockAdjustmentOut(BaseModel):
    id: str
    item_code: str
    previous_qty: int
    counted_qty: int
    delta: int
    reason: str
    note: str | None = None
    adjusted_by: str
    created_at: datetime | None = None
