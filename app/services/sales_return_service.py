"""Section 16.3 — Sales Return. Distinct from a Correction Entry (which fixes
a data-entry mistake): a Return is a real event — goods physically come back.
Restores stock and credits the party's balance via a 'receiving'-type ledger
row (same balance-chain math as Record Payment, Section 5.0), never touching
the original invoice's own rows (matching Section 5.1's 'never rewrite
history' principle, applied here to a different kind of event)."""

from datetime import date

from supabase import Client

from app.models.sales_return import SalesReturnCreate, SalesReturnOut
from app.services import activity_log_service, ledger_math
from app.services.inventory_service import adjust_stock
from app.services.ledger_service import LINE_ITEMS_TABLE, PARENT_COLUMN, require_invoice
from app.services.line_items import fetch_line_items
from app.services.party_service import get_latest_party_balance


class InvoiceNotFinalizedForReturnError(Exception):
    """Section 16.3: 'restricted to already-finalized invoices.'"""


class ItemNotOnInvoiceError(Exception):
    pass


class ReturnQtyExceedsOriginalError(Exception):
    pass


def _row_to_out(row: dict) -> SalesReturnOut:
    return SalesReturnOut(
        id=row["id"],
        original_invoice_id=row["original_invoice_id"],
        item_code=row["item_code"],
        qty_returned=row["qty_returned"],
        reason=row.get("reason"),
        ledger_credit_id=row.get("ledger_credit_id"),
        processed_by=row["processed_by"],
        created_at=row.get("created_at"),
    )


def create_sales_return(supabase: Client, invoice_id: str, data: SalesReturnCreate, user_id: str) -> SalesReturnOut:
    invoice = require_invoice(supabase, invoice_id)
    if invoice["invoice_state"] != "finalized" or invoice["txn_type"] != "sale":
        raise InvoiceNotFinalizedForReturnError("Return Items only applies to an already-finalized sale invoice")

    item_code = data.item_code.upper()
    lines = fetch_line_items(supabase, LINE_ITEMS_TABLE, PARENT_COLUMN, invoice_id)
    line = next((l for l in lines if l["item_code"] == item_code), None)
    if line is None:
        raise ItemNotOnInvoiceError(f"'{item_code}' is not a line item on this invoice")

    already_returned = sum(
        r["qty_returned"]
        for r in supabase.table("sales_returns")
        .select("qty_returned")
        .eq("original_invoice_id", invoice_id)
        .eq("item_code", item_code)
        .execute()
        .data
    )
    remaining = line["qty"] - already_returned
    if data.qty_returned > remaining:
        raise ReturnQtyExceedsOriginalError(
            f"Cannot return {data.qty_returned} — only {remaining} of the {line['qty']} sold on this line remain returnable "
            f"({already_returned} already returned)"
        )

    adjust_stock(supabase, item_code, data.qty_returned)  # goods physically came back — stock increases

    credit_amount = ledger_math.round2(float(line["rate"]) * data.qty_returned)
    previous_balance = get_latest_party_balance(supabase, invoice["party_id"])
    current_balance = ledger_math.compute_receiving_balance(previous_balance, credit_amount)

    invoice_no = invoice.get("invoice_no") or invoice_id
    ledger_payload = {
        "party_id": invoice["party_id"],
        "invoice_state": "finalized",
        "invoice_status": "paid",
        "txn_type": "receiving",
        "transaction_date": date.today().isoformat(),
        "discount_amount": "0",
        "total_amount": str(credit_amount),
        "previous_balance": str(previous_balance),
        "current_balance": str(current_balance),
        "approval_status": "approved",  # a credit back to the customer never gates, same as Record Payment
        "payment_note": f"Sales Return: {data.qty_returned}x {item_code} from Invoice #{invoice_no}",
    }
    ledger_resp = supabase.table("customer_ledgers").insert(ledger_payload).execute()
    ledger_credit_id = ledger_resp.data[0]["id"]

    return_payload = {
        "original_invoice_id": invoice_id,
        "item_code": item_code,
        "qty_returned": data.qty_returned,
        "reason": data.reason,
        "ledger_credit_id": ledger_credit_id,
        "processed_by": user_id,
    }
    resp = supabase.table("sales_returns").insert(return_payload).execute()

    activity_log_service.log_activity(
        supabase,
        user_id,
        "sales_return",
        f"Returned {data.qty_returned}x {item_code} from Invoice #{invoice_no}, credited Rs. {credit_amount:,.2f}",
    )

    return _row_to_out(resp.data[0])


def list_returns_for_invoice(supabase: Client, invoice_id: str) -> list[SalesReturnOut]:
    resp = (
        supabase.table("sales_returns")
        .select("*")
        .eq("original_invoice_id", invoice_id)
        .order("created_at", desc=True)
        .execute()
    )
    return [_row_to_out(row) for row in resp.data]
