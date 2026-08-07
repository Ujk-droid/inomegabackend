"""Section 5.4.B — Purchase module (stock in, mirror of Sale).

Unlike customer_ledgers, the PRD gives purchases no draft/finalized state — every
purchase row is created complete: auto-numbered and stock-incremented immediately,
since 5.4.B describes it as a straightforward "buying stock from suppliers" entry,
not a dispatched customer-facing document that needs a review/lock step.

purchases is header-only; its line items live in purchase_line_items, one row
per product per purchase (same multi-item fix as customer_ledgers/invoice_line_items).
"""

from supabase import Client

from app.models.ledger import LineItemOut
from app.models.purchase import PurchaseCreate, PurchaseOut
from app.services import ledger_hooks, ledger_math
from app.services.inventory_service import adjust_stock
from app.services.line_items import fetch_line_items, insert_line_items, resolve_and_verify_lines
from app.services.party_service import require_party

LINE_ITEMS_TABLE = "purchase_line_items"
PARENT_COLUMN = "purchase_id"


def _line_out(row: dict) -> LineItemOut:
    return LineItemOut(
        id=row["id"],
        item_code=row["item_code"],
        qty=row["qty"],
        rate=float(row["rate"]),
        line_total=float(row["line_total"]),
        line_number=row["line_number"],
    )


def row_to_out(supabase: Client, row: dict) -> PurchaseOut:
    lines = fetch_line_items(supabase, LINE_ITEMS_TABLE, PARENT_COLUMN, row["id"])
    return PurchaseOut(
        id=row["id"],
        purchase_bill_no=row.get("purchase_bill_no"),
        party_id=row["party_id"],
        transaction_date=row["transaction_date"],
        discount_amount=float(row.get("discount_amount") or 0),
        total_amount=float(row["total_amount"]),
        received_amount=float(row.get("received_amount") or 0),
        previous_balance=float(row.get("previous_balance") or 0),
        current_balance=float(row["current_balance"]),
        line_items=[_line_out(r) for r in lines],
        created_at=row.get("created_at"),
    )


def fetch_purchase(supabase: Client, purchase_id: str) -> dict | None:
    resp = supabase.table("purchases").select("*").eq("id", purchase_id).limit(1).execute()
    return resp.data[0] if resp.data else None


def _existing_bill_numbers(supabase: Client) -> list[str | None]:
    resp = supabase.table("purchases").select("purchase_bill_no").execute()
    return [row.get("purchase_bill_no") for row in resp.data]


def get_latest_purchase_balance(supabase: Client, party_id: str) -> float:
    """Mirrors party_service.get_latest_party_balance: anchored on created_at
    (insertion order), not transaction_date — see that function's docstring for
    why. This is a running prefix-sum; transaction_date only drives display
    order (list_party_purchases/list_purchases below)."""
    resp = (
        supabase.table("purchases")
        .select("current_balance")
        .eq("party_id", party_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not resp.data:
        return 0.0
    return float(resp.data[0]["current_balance"])


def create_purchase(supabase: Client, data: PurchaseCreate) -> PurchaseOut:
    require_party(supabase, data.party_id)

    resolved_lines = resolve_and_verify_lines(supabase, data.line_items)
    line_totals = [line["line_total"] for line in resolved_lines]
    total_amount = ledger_math.compute_invoice_total(line_totals, data.discount_amount)
    ledger_hooks.verify_invoice_math(line_totals, data.discount_amount, total_amount)

    previous_balance = get_latest_purchase_balance(supabase, data.party_id)
    current_balance = ledger_math.compute_purchase_balance(previous_balance, total_amount)
    ledger_hooks.verify_purchase_balance(previous_balance, total_amount, current_balance)

    bill_no = ledger_math.next_sequence_number(_existing_bill_numbers(supabase))

    for line in resolved_lines:
        adjust_stock(supabase, line["item_code"], line["qty"])  # Purchase increases stock (5.4.B), per line

    payload = {
        "purchase_bill_no": bill_no,
        "party_id": data.party_id,
        "transaction_date": data.transaction_date.isoformat(),
        "discount_amount": str(data.discount_amount),
        "total_amount": str(total_amount),
        "received_amount": str(data.received_amount),
        "previous_balance": str(previous_balance),
        "current_balance": str(current_balance),
    }
    resp = supabase.table("purchases").insert(payload).execute()
    purchase_id = resp.data[0]["id"]
    insert_line_items(supabase, LINE_ITEMS_TABLE, PARENT_COLUMN, purchase_id, resolved_lines)
    return row_to_out(supabase, fetch_purchase(supabase, purchase_id))


def list_party_purchases(supabase: Client, party_id: str) -> list[PurchaseOut]:
    resp = (
        supabase.table("purchases")
        .select("*")
        .eq("party_id", party_id)
        .order("transaction_date", desc=True)
        .order("created_at", desc=True)
        .execute()
    )
    return [row_to_out(supabase, row) for row in resp.data]


def list_purchases(supabase: Client) -> list[PurchaseOut]:
    """Every purchase across all suppliers, newest first — Screen 15's list
    view (Section 5.4.B), the mirror of ledger_service.list_invoices."""
    resp = supabase.table("purchases").select("*").order("transaction_date", desc=True).order("created_at", desc=True).execute()
    return [row_to_out(supabase, row) for row in resp.data]
