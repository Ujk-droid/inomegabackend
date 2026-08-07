from pydantic import BaseModel


class ScanSlipItemOut(BaseModel):
    raw_description: str
    qty: int
    rate: float | None = None
    matched_item_code: str | None = None
    matched_item_name: str | None = None
    confidence: str  # 'high' | 'low' | 'none' — 'none' means no confident match, pick manually


class ScanSlipResult(BaseModel):
    scan_slip_cloudinary_url: str
    items: list[ScanSlipItemOut]
