"""Section 16.5 — Delivery Challan: a simpler delivery-note PDF (no pricing),
generated once per finalized invoice via pdf_service's shared _render_bill_pdf
'sibling mode.' Marked with a delivery date once actually delivered."""

from datetime import date

from supabase import Client

from app.models.delivery_challan import DeliveryChallanOut
from app.services import activity_log_service, cloudinary_client, ledger_math, pdf_service
from app.services.invoice_dispatch_service import _items_by_code
from app.services.ledger_service import LINE_ITEMS_TABLE, PARENT_COLUMN, require_invoice
from app.services.line_items import fetch_line_items
from app.services.party_service import get_party


class InvoiceNotFinalizedForChallanError(Exception):
    """A Delivery Challan can only be generated from an already-finalized invoice."""


class ChallanAlreadyExistsError(Exception):
    """Section 16.5: 'Can be generated once per invoice.'"""


class ChallanNotFoundError(Exception):
    pass


def row_to_out(row: dict) -> DeliveryChallanOut:
    return DeliveryChallanOut(
        id=row["id"],
        invoice_id=row["invoice_id"],
        challan_no=row.get("challan_no"),
        delivered_at=row.get("delivered_at"),
        pdf_cloudinary_url=row.get("pdf_cloudinary_url"),
        created_by=row["created_by"],
        created_at=row.get("created_at"),
    )


def _existing_challan_numbers(supabase: Client) -> list[str | None]:
    resp = supabase.table("delivery_challans").select("challan_no").execute()
    return [row.get("challan_no") for row in resp.data]


def get_challan_for_invoice(supabase: Client, invoice_id: str) -> dict | None:
    resp = supabase.table("delivery_challans").select("*").eq("invoice_id", invoice_id).limit(1).execute()
    return resp.data[0] if resp.data else None


def create_delivery_challan(supabase: Client, invoice_id: str, user_id: str) -> DeliveryChallanOut:
    invoice = require_invoice(supabase, invoice_id)
    if invoice["invoice_state"] != "finalized":
        raise InvoiceNotFinalizedForChallanError("A Delivery Challan can only be generated from a finalized invoice")

    if get_challan_for_invoice(supabase, invoice_id) is not None:
        raise ChallanAlreadyExistsError("A Delivery Challan already exists for this invoice")

    party = get_party(supabase, invoice["party_id"])
    line_items = fetch_line_items(supabase, LINE_ITEMS_TABLE, PARENT_COLUMN, invoice_id)
    items_by_code = _items_by_code(supabase, line_items)

    challan_no = ledger_math.next_sequence_number(_existing_challan_numbers(supabase))
    challan = {"challan_no": challan_no, "delivered_at": None}
    pdf_bytes = pdf_service.build_delivery_challan_pdf(challan, invoice, party, line_items, items_by_code)
    pdf_url, _public_id = cloudinary_client.upload_delivery_challan_pdf(pdf_bytes, challan_no)

    payload = {
        "invoice_id": invoice_id,
        "challan_no": challan_no,
        "pdf_cloudinary_url": pdf_url,
        "created_by": user_id,
    }
    resp = supabase.table("delivery_challans").insert(payload).execute()
    activity_log_service.log_activity(
        supabase,
        user_id,
        "delivery_challan_generated",
        f"Generated Delivery Challan #{challan_no} for Invoice #{invoice.get('invoice_no') or invoice_id}",
    )
    return row_to_out(resp.data[0])


def require_challan(supabase: Client, challan_id: str) -> dict:
    resp = supabase.table("delivery_challans").select("*").eq("id", challan_id).limit(1).execute()
    if not resp.data:
        raise ChallanNotFoundError(f"Delivery Challan '{challan_id}' not found")
    return resp.data[0]


def mark_delivered(supabase: Client, challan_id: str, delivered_at: date, user_id: str) -> DeliveryChallanOut:
    challan = require_challan(supabase, challan_id)
    supabase.table("delivery_challans").update({"delivered_at": delivered_at.isoformat()}).eq("id", challan_id).execute()
    activity_log_service.log_activity(
        supabase,
        user_id,
        "delivery_challan_marked_delivered",
        f"Marked Delivery Challan #{challan['challan_no']} as delivered on {delivered_at.isoformat()}",
    )
    return row_to_out(require_challan(supabase, challan_id))
