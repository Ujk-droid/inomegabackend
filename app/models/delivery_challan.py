from datetime import date, datetime

from pydantic import BaseModel


class DeliveryChallanOut(BaseModel):
    id: str
    invoice_id: str
    challan_no: str | None = None
    delivered_at: date | None = None
    pdf_cloudinary_url: str | None = None
    created_by: str
    created_at: datetime | None = None


class DeliveryChallanMarkDelivered(BaseModel):
    delivered_at: date
