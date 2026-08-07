from datetime import date, datetime

from pydantic import BaseModel, Field


class LineItemCreate(BaseModel):
    item_code: str
    qty: int = Field(..., gt=0)
    rate: float | None = Field(default=None, gt=0)  # None = use inventory_items.rate (catalog default)


class LineItemOut(BaseModel):
    id: str
    item_code: str
    qty: int
    rate: float
    line_total: float
    line_number: int


class SaleDraftCreate(BaseModel):
    party_id: str
    line_items: list[LineItemCreate] = Field(..., min_length=1)
    discount_amount: float = Field(default=0.0, ge=0)
    transaction_date: date
    received_at_sale: float = Field(default=0.0, ge=0)
    # Section 5.4.K — set when this invoice was built (in full or in part) from
    # a POST /invoices/scan-slip result; the original slip stays attached as a
    # reference. None for the ordinary manual-entry path (most invoices).
    scan_slip_cloudinary_url: str | None = None


class SaleDraftUpdate(BaseModel):
    line_items: list[LineItemCreate] | None = None  # None = leave line items unchanged
    discount_amount: float | None = Field(default=None, ge=0)
    transaction_date: date | None = None
    received_at_sale: float | None = Field(default=None, ge=0)
    scan_slip_cloudinary_url: str | None = None


class RecordPaymentCreate(BaseModel):
    party_id: str
    amount: float = Field(..., gt=0)
    method: str = Field(..., description="Name from the particulars master table, e.g. 'Cash', 'Cheque'")
    bank_name: str | None = Field(default=None, description="Name from bank_accounts, e.g. 'Meezan Bank', 'Cash Received'")
    payment_reference: str | None = None
    payment_note: str | None = None
    transaction_date: date


class CorrectionCreate(BaseModel):
    reason: str = Field(..., min_length=1)
    line_items: list[LineItemCreate] | None = None  # None = keep the original's line items
    discount_amount: float | None = Field(default=None, ge=0)  # None = keep the original's discount


class PaymentCorrectionCreate(BaseModel):
    """Section 16.6 — 'Fix This Payment.' None on a field means 'unchanged
    from the original payment' — only the fields actually wrong need to be given."""

    reason: str = Field(..., min_length=1)
    corrected_amount: float | None = Field(default=None, gt=0)
    corrected_method: str | None = None  # a particulars name, e.g. 'Cheque'
    corrected_date: date | None = None


class ShareEmailCreate(BaseModel):
    """Section 9.2 Share on Email. to_email is optional — None means 'use the
    party's own parties.email on file'; given, it overrides that default for
    this one send (e.g. a different contact the customer asked to be cc'd
    instead of, or a one-off correction when the stored email is stale)."""

    to_email: str | None = Field(default=None, min_length=3)


class InvoiceOut(BaseModel):
    id: str
    party_id: str
    invoice_no: str | None = None
    invoice_state: str
    correction_of: str | None = None
    correction_reason: str | None = None
    payment_correction_of: str | None = None
    payment_correction_reason: str | None = None
    due_date: date | None = None
    invoice_status: str
    txn_type: str
    particular_id: str | None = None
    bank_account_id: str | None = None
    payment_reference: str | None = None
    payment_note: str | None = None
    transaction_date: date
    discount_amount: float
    total_amount: float
    received_at_sale: float
    previous_balance: float
    current_balance: float
    approval_status: str
    can_dispatch: bool
    line_items: list[LineItemOut]
    scan_slip_cloudinary_url: str | None = None
    created_at: datetime | None = None
