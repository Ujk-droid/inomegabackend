"""Section 9.2 — generate/share-email/whatsapp-link/reprint, plus a live
preview (build_preview_pdf) for an unsaved draft. All four dispatch actions
are gated the same way: blocked until the invoice's Human Gate (Section 7.4)
approval clears, so WhatsApp/email can never be used to route around it. The
preview is exempt from that gate on purpose — it never leaves the response
body (no Cloudinary upload, no DB write), so there's nothing to dispatch."""

from supabase import Client

from app.models.ledger import SaleDraftCreate
from app.services import cloudinary_client, email_service, ledger_math, party_service, pdf_service, whatsapp_service
from app.services.inventory_service import fetch_item_by_code
from app.services.ledger_service import LINE_ITEMS_TABLE, PARENT_COLUMN, require_invoice
from app.services.line_items import fetch_line_items, resolve_and_verify_lines


class DispatchNotAllowedError(Exception):
    """Raised when generate/share-email/whatsapp-link/reprint is attempted on
    an invoice still pending Human Gate approval (Section 9.2/7.4)."""


def _require_dispatchable(invoice: dict) -> None:
    if invoice["approval_status"] != "approved":
        raise DispatchNotAllowedError(
            "This invoice is awaiting Human Gate approval — dispatch is blocked until an Admin approves it"
        )


def _items_by_code(supabase: Client, line_items: list[dict]) -> dict[str, dict]:
    """Real bug fixed here: pdf_service.py's item table reads item.get("unit_name"),
    but fetch_item_by_code's raw row only ever had an embedded unit_ref: {name}
    (ITEM_SELECT's postgrest embed) — unit_name never existed, so every PDF's
    Unit column silently always fell back to "pcs" regardless of the item's
    real unit. Flattened here, once, for every caller of this helper (both the
    real dispatch path and the new preview path below)."""
    codes = {line["item_code"] for line in line_items}
    result = {}
    for code in codes:
        row = fetch_item_by_code(supabase, code) or {}
        unit_ref = row.get("unit_ref")
        if unit_ref:
            row = {**row, "unit_name": unit_ref.get("name")}
        result[code] = row
    return result


def build_preview_pdf(supabase: Client, data: SaleDraftCreate) -> bytes:
    """Section 9.2's 'live PDF preview' for the Invoice Builder — same math
    and same build_invoice_pdf renderer as the real dispatch path, computed
    from the in-progress form state directly. Nothing is persisted: no draft
    row, no line items, no Cloudinary upload — a pure read producing bytes."""
    party = party_service.require_party(supabase, data.party_id)
    resolved_lines = resolve_and_verify_lines(supabase, data.line_items)
    for line_number, line in enumerate(resolved_lines, start=1):
        line["line_number"] = line_number

    total_amount = ledger_math.compute_invoice_total(
        [line["line_total"] for line in resolved_lines], data.discount_amount
    )
    previous_balance = party_service.get_latest_party_balance(supabase, data.party_id)
    current_balance = ledger_math.compute_sale_balance(previous_balance, total_amount)

    invoice = {
        "invoice_no": None,
        "transaction_date": data.transaction_date.isoformat(),
        "total_amount": total_amount,
        "previous_balance": previous_balance,
        "discount_amount": data.discount_amount,
        "current_balance": current_balance,
        "received_at_sale": data.received_at_sale,
    }
    items_by_code = _items_by_code(supabase, resolved_lines)
    return pdf_service.build_invoice_pdf(invoice, party, resolved_lines, items_by_code)


def generate_invoice_pdf(supabase: Client, invoice_id: str, *, duplicate: bool = False) -> str:
    """Builds the PDF, uploads it to Cloudinary, and — for the original (non-
    duplicate) generation — stores pdf_cloudinary_url on the invoice. A
    duplicate reprint returns its own URL without touching the original row
    (Section 9.2: 'the original invoice and its PDF remain untouched')."""
    invoice = require_invoice(supabase, invoice_id)
    _require_dispatchable(invoice)

    party = party_service.get_party(supabase, invoice["party_id"])
    line_items = fetch_line_items(supabase, LINE_ITEMS_TABLE, PARENT_COLUMN, invoice_id)
    items_by_code = _items_by_code(supabase, line_items)

    pdf_bytes = pdf_service.build_invoice_pdf(invoice, party, line_items, items_by_code, duplicate=duplicate)
    invoice_no = invoice.get("invoice_no") or invoice_id
    url, _public_id = cloudinary_client.upload_invoice_pdf(pdf_bytes, invoice_no, duplicate=duplicate)

    if not duplicate:
        supabase.table("customer_ledgers").update({"pdf_cloudinary_url": url}).eq("id", invoice_id).execute()

    return url


def share_invoice_email(supabase: Client, invoice_id: str, to_email: str | None = None) -> None:
    """to_email overrides the party's own parties.email on file for this one
    send (Section 9.2's UI editable-email-field); falls back to it when not
    given. The PDF is attached as real bytes, not just linked in the body —
    a customer opening this on their phone shouldn't have to leave the email
    app to see the invoice. The Cloudinary link is kept in the body too, as a
    second, always-reachable copy."""
    invoice = require_invoice(supabase, invoice_id)
    _require_dispatchable(invoice)

    party = party_service.get_party(supabase, invoice["party_id"])
    recipient = (to_email or "").strip() or (party.get("email") if party else None)
    if not recipient:
        raise email_service.EmailDispatchError(
            "No email address given, and this party has no email address on file"
        )

    line_items = fetch_line_items(supabase, LINE_ITEMS_TABLE, PARENT_COLUMN, invoice_id)
    items_by_code = _items_by_code(supabase, line_items)
    pdf_bytes = pdf_service.build_invoice_pdf(invoice, party, line_items, items_by_code)

    pdf_url = invoice.get("pdf_cloudinary_url") or generate_invoice_pdf(supabase, invoice_id)
    invoice_no = invoice.get("invoice_no") or invoice_id
    party_name = party["party_name"] if party else "Customer"
    email_service.send_email(
        recipient,
        f"Omega Scales — Invoice #{invoice_no}",
        f"Dear {party_name},\n\nPlease find your invoice attached.\n\n"
        f"You can also view it online here: {pdf_url}\n\n"
        f"Total: Rs. {float(invoice['total_amount']):,.2f}\n"
        f"Pay Dues within 15 Days.\n\nThank you for your business!",
        attachment=(f"Invoice-{invoice_no}.pdf", pdf_bytes),
    )


def build_invoice_whatsapp_link(supabase: Client, invoice_id: str) -> str:
    invoice = require_invoice(supabase, invoice_id)
    _require_dispatchable(invoice)

    party = party_service.get_party(supabase, invoice["party_id"])
    pdf_url = invoice.get("pdf_cloudinary_url") or generate_invoice_pdf(supabase, invoice_id)
    return whatsapp_service.build_whatsapp_link(
        party.get("phone") if party else None,
        invoice.get("invoice_no"),
        pdf_url,
        float(invoice["total_amount"]),
    )


def reprint_invoice_pdf(supabase: Client, invoice_id: str) -> str:
    """Section 9.2 Duplicate reprint — same content, diagonal DUPLICATE watermark."""
    require_invoice(supabase, invoice_id)  # 404s consistently even though generate_invoice_pdf also checks
    return generate_invoice_pdf(supabase, invoice_id, duplicate=True)
