"""Section 5.4.B / 9.2 — PDF generation for Purchase Bills, mirroring
invoice_dispatch_service.py's preview/dispatch split: a live preview for an
unsaved form (build_purchase_preview_pdf, shows "DRAFT" for the bill number,
nothing persisted) and the real render for an already-created purchase
(build_purchase_pdf_for, the actual assigned purchase_bill_no). Purchases have
no Human Gate and no email/WhatsApp dispatch (Section 5.4.B: "written in a
single step") so there's no Cloudinary upload step here — just PDF bytes."""

from supabase import Client

from app.models.purchase import PurchaseCreate
from app.services import ledger_math, party_service, pdf_service
from app.services.invoice_dispatch_service import _items_by_code
from app.services.line_items import fetch_line_items, resolve_and_verify_lines
from app.services.purchase_service import LINE_ITEMS_TABLE, PARENT_COLUMN, get_latest_purchase_balance


def build_purchase_preview_pdf(supabase: Client, data: PurchaseCreate) -> bytes:
    """Same pattern as invoice_dispatch_service.build_preview_pdf — computed
    from the in-progress form state directly, nothing persisted."""
    party = party_service.require_party(supabase, data.party_id)
    resolved_lines = resolve_and_verify_lines(supabase, data.line_items)
    for line_number, line in enumerate(resolved_lines, start=1):
        line["line_number"] = line_number

    total_amount = ledger_math.compute_invoice_total(
        [line["line_total"] for line in resolved_lines], data.discount_amount
    )
    previous_balance = get_latest_purchase_balance(supabase, data.party_id)
    current_balance = ledger_math.compute_purchase_balance(previous_balance, total_amount)

    purchase = {
        "purchase_bill_no": None,
        "transaction_date": data.transaction_date.isoformat(),
        "total_amount": total_amount,
        "previous_balance": previous_balance,
        "discount_amount": data.discount_amount,
        "current_balance": current_balance,
        "received_amount": data.received_amount,
    }
    items_by_code = _items_by_code(supabase, resolved_lines)
    return pdf_service.build_purchase_pdf(purchase, party, resolved_lines, items_by_code)


def build_purchase_pdf_for(supabase: Client, purchase_row: dict) -> bytes:
    """Renders the real PDF for an already-created purchase (its actual
    purchase_bill_no, party, and saved line items) — used by 'Print & Save'
    right after create_purchase, so the printed bill shows the real assigned
    number instead of the preview's 'DRAFT' placeholder."""
    party = party_service.get_party(supabase, purchase_row["party_id"])
    line_items = fetch_line_items(supabase, LINE_ITEMS_TABLE, PARENT_COLUMN, purchase_row["id"])
    items_by_code = _items_by_code(supabase, line_items)
    return pdf_service.build_purchase_pdf(purchase_row, party, line_items, items_by_code)
