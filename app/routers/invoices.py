from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from supabase import Client

from app.database import get_supabase
from app.dependencies import get_current_user, require_admin
from app.models.delivery_challan import DeliveryChallanOut
from app.models.ledger import (
    CorrectionCreate,
    InvoiceOut,
    PaymentCorrectionCreate,
    RecordPaymentCreate,
    SaleDraftCreate,
    SaleDraftUpdate,
    ShareEmailCreate,
)
from app.models.sales_return import SalesReturnCreate, SalesReturnOut
from app.models.scan_slip import ScanSlipResult
from app.services import activity_log_service
from app.services.inventory_service import InsufficientStockError, ItemNotFoundError
from app.services.ledger_hooks import LedgerIntegrityError
from app.services.sales_return_service import (
    InvoiceNotFinalizedForReturnError,
    ItemNotOnInvoiceError,
    ReturnQtyExceedsOriginalError,
    create_sales_return,
    list_returns_for_invoice,
)
from app.services.ledger_service import (
    CreditLimitExceededError,
    InvoiceNotDraftError,
    InvoiceNotFinalizedError,
    InvoiceNotFoundError,
    PaymentNotFoundError,
    approve_invoice,
    create_correction,
    create_draft_sale,
    create_payment_correction,
    fetch_invoice,
    finalize_invoice,
    list_invoices,
    record_payment,
    reject_invoice,
    row_to_out,
    update_draft,
)
from app.services.delivery_challan_service import (
    ChallanAlreadyExistsError,
    InvoiceNotFinalizedForChallanError,
    create_delivery_challan,
    get_challan_for_invoice,
    row_to_out as challan_row_to_out,
)
from app.services.invoice_dispatch_service import (
    DispatchNotAllowedError,
    build_invoice_whatsapp_link,
    build_preview_pdf,
    generate_invoice_pdf,
    reprint_invoice_pdf,
    share_invoice_email,
)
from app.services.email_service import EmailDispatchError
from app.services.master_data import UnknownReferenceError
from app.services.party_service import PartyNotFoundError
from app.services.scan_slip_service import ScanSlipError, scan_slip
from app.services.whatsapp_service import MissingPhoneNumberError

router = APIRouter(prefix="/api/v1/invoices", tags=["invoices"])


@router.get("", response_model=list[InvoiceOut])
def list_invoices_endpoint(user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)):
    """Screen 6's stats strip + table, and the Dashboard's Total Sales/Outstanding/
    Pending Approvals KPI cards (Section 6, Screen 2) — all derived client-side
    from this same list rather than a separate duplicated aggregate endpoint."""
    return list_invoices(supabase)


@router.post("/draft", response_model=InvoiceOut, status_code=201)
def create_draft_invoice(
    data: SaleDraftCreate, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    """Section 5.1 — draft invoices are fully editable, no invoice_no is assigned yet."""
    try:
        return create_draft_sale(supabase, data)
    except PartyNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LedgerIntegrityError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/preview-pdf")
def preview_invoice_pdf_endpoint(
    data: SaleDraftCreate, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    """Section 9.2's 'live PDF preview' — Invoice Builder calls this as items
    are added, before any draft exists. Nothing is persisted or gated by the
    Human Gate (there's nothing to dispatch yet, just bytes in the response)."""
    try:
        pdf_bytes = build_preview_pdf(supabase, data)
    except PartyNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(content=pdf_bytes, media_type="application/pdf")


@router.post("/scan-slip", response_model=ScanSlipResult)
async def scan_slip_endpoint(
    file: UploadFile = File(...), user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    """Section 5.4.K — reads a photographed/uploaded order slip via OpenAI
    Vision and returns a review list; nothing is added to any invoice here.
    The Invoice Builder shows this list for confirmation and only adds items
    the person actually accepts."""
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are accepted")
    contents = await file.read()
    try:
        return scan_slip(supabase, contents)
    except ScanSlipError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{invoice_id}", response_model=InvoiceOut)
def get_invoice(
    invoice_id: str, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    row = fetch_invoice(supabase, invoice_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_id}' not found")
    return row_to_out(supabase, row)


@router.put("/{invoice_id}", response_model=InvoiceOut)
def edit_draft_invoice(
    invoice_id: str,
    data: SaleDraftUpdate,
    user: dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Direct-edit path of the single 'Edit' button (Section 5.1) — only reachable
    while the invoice is still draft; a finalized invoice must go through /correct."""
    try:
        return update_draft(supabase, invoice_id, data)
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvoiceNotDraftError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LedgerIntegrityError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{invoice_id}/finalize", response_model=InvoiceOut)
def finalize_invoice_endpoint(
    invoice_id: str,
    override_credit_limit: bool = Query(False),
    user: dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Section 5.3 — assigns invoice_no, sets due_date, decrements stock, and runs
    the Section 7.4 Human Gate check (total_amount > threshold -> approval_status='pending').
    Section 16.1 — also enforces the party's credit_limit; override_credit_limit
    is Admin-only ('Approve anyway')."""
    if override_credit_limit and user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only Admin can override a credit limit block")
    try:
        return finalize_invoice(supabase, invoice_id, user=user, override_credit_limit=override_credit_limit)
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvoiceNotDraftError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InsufficientStockError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CreditLimitExceededError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{invoice_id}/approve", response_model=InvoiceOut)
def approve_invoice_endpoint(
    invoice_id: str, admin: dict = Depends(require_admin), supabase: Client = Depends(get_supabase)
):
    """Section 7.4 Human Gate Drawer — Admin-only in the app's RBAC (Section 3),
    now enforced."""
    try:
        return approve_invoice(supabase, invoice_id)
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{invoice_id}/reject", response_model=InvoiceOut)
def reject_invoice_endpoint(
    invoice_id: str, admin: dict = Depends(require_admin), supabase: Client = Depends(get_supabase)
):
    try:
        return reject_invoice(supabase, invoice_id)
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{invoice_id}/correct", response_model=InvoiceOut, status_code=201)
def correct_invoice_endpoint(
    invoice_id: str,
    data: CorrectionCreate,
    admin: dict = Depends(require_admin),
    supabase: Client = Depends(get_supabase),
):
    """'Fix This Invoice' (Section 5.1) — the other half of the single Edit button.
    Never modifies the original row; creates a new Correction Entry instead.
    Admin-only (Section 3: 'ledger edits (via Correction Entry)' is an Admin permission)."""
    original = fetch_invoice(supabase, invoice_id)
    try:
        corrected = create_correction(supabase, invoice_id, data)
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvoiceNotFinalizedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LedgerIntegrityError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    invoice_label = original.get("invoice_no") if original else invoice_id
    activity_log_service.log_activity(
        supabase, admin["id"], "invoice_corrected", f"Corrected Invoice #{invoice_label}: {data.reason}"
    )
    return corrected


@router.post("/{invoice_id}/returns", response_model=SalesReturnOut, status_code=201)
def create_sales_return_endpoint(
    invoice_id: str,
    data: SalesReturnCreate,
    user: dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Section 16.3 — 'Return Items,' Admin/Staff both, restricted to
    already-finalized invoices. Restores stock, credits the party's balance."""
    try:
        return create_sales_return(supabase, invoice_id, data, user["id"])
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvoiceNotFinalizedForReturnError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ItemNotOnInvoiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ReturnQtyExceedsOriginalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{invoice_id}/returns", response_model=list[SalesReturnOut])
def list_sales_returns_endpoint(
    invoice_id: str, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    return list_returns_for_invoice(supabase, invoice_id)


@router.post("/payments", response_model=InvoiceOut, status_code=201)
def record_payment_endpoint(
    data: RecordPaymentCreate, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    """Section 5.0 — Record Payment. Always approval_status='approved': a payment
    reduces debt, it never goes through the Human Gate (Section 12.1)."""
    try:
        return record_payment(supabase, data)
    except PartyNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UnknownReferenceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LedgerIntegrityError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{invoice_id}/delivery-challan", response_model=DeliveryChallanOut, status_code=201)
def create_delivery_challan_endpoint(
    invoice_id: str, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    """Section 16.5 — 'Generate Delivery Challan,' Admin/Staff both, restricted
    to already-finalized invoices; can only be generated once per invoice."""
    try:
        return create_delivery_challan(supabase, invoice_id, user["id"])
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvoiceNotFinalizedForChallanError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ChallanAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{invoice_id}/delivery-challan", response_model=DeliveryChallanOut)
def get_delivery_challan_endpoint(
    invoice_id: str, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    challan = get_challan_for_invoice(supabase, invoice_id)
    if challan is None:
        raise HTTPException(status_code=404, detail="No Delivery Challan exists for this invoice yet")
    return challan_row_to_out(challan)


@router.post("/payments/{payment_id}/correct", response_model=InvoiceOut, status_code=201)
def correct_payment_endpoint(
    payment_id: str,
    data: PaymentCorrectionCreate,
    admin: dict = Depends(require_admin),
    supabase: Client = Depends(get_supabase),
):
    """'Fix This Payment' (Section 16.6) — the same single-Edit-button pattern as
    /invoices/{id}/correct (Section 5.1), now applied to a recorded payment.
    Never modifies the original row; creates a signed-delta correction row
    instead. Admin-only, same rationale as invoice corrections."""
    try:
        return create_payment_correction(supabase, payment_id, data, admin["id"])
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PaymentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LedgerIntegrityError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{invoice_id}/generate")
def generate_invoice_endpoint(
    invoice_id: str, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    """Section 9.2 — builds the PDF, uploads to Cloudinary, stores
    pdf_cloudinary_url. Blocked until Human Gate approval clears."""
    try:
        url = generate_invoice_pdf(supabase, invoice_id)
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DispatchNotAllowedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"pdf_url": url}


@router.post("/{invoice_id}/share-email")
def share_invoice_email_endpoint(
    invoice_id: str,
    payload: ShareEmailCreate | None = None,
    user: dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Section 9.2 — Gmail App Password SMTP send, real PDF attached (not just
    linked). Blocked until Human Gate approval clears, same as the WhatsApp
    link below. payload.to_email is optional — omitted/empty body falls back
    to the party's own parties.email, same as before this field existed."""
    try:
        share_invoice_email(supabase, invoice_id, to_email=payload.to_email if payload else None)
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DispatchNotAllowedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except EmailDispatchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"status": "sent"}


@router.get("/{invoice_id}/whatsapp-link")
def invoice_whatsapp_link_endpoint(
    invoice_id: str, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    """Section 9.2 — a wa.me click-to-chat link the app constructs; Admin/Staff
    reviews and presses Send themselves. Same Human Gate rule as email/generate,
    so WhatsApp can't be used to bypass it."""
    try:
        link = build_invoice_whatsapp_link(supabase, invoice_id)
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DispatchNotAllowedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except MissingPhoneNumberError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"whatsapp_url": link}


@router.post("/{invoice_id}/reprint")
def reprint_invoice_endpoint(
    invoice_id: str, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    """Section 9.2 Duplicate reprint — identical PDF plus a diagonal DUPLICATE
    watermark; the original invoice/PDF are never touched."""
    try:
        url = reprint_invoice_pdf(supabase, invoice_id)
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DispatchNotAllowedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"pdf_url": url}
