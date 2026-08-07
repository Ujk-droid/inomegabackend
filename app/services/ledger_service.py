"""Section 5.0/5.1/5.3, Section 7.4 — Invoice + Ledger business logic.

customer_ledgers is a header-only row (Section 5's multi-item fix); its line
items live in invoice_line_items, one row per product per invoice.
"""

from datetime import date

from supabase import Client

from app.models.ledger import (
    CorrectionCreate,
    InvoiceOut,
    LineItemOut,
    PaymentCorrectionCreate,
    RecordPaymentCreate,
    SaleDraftCreate,
    SaleDraftUpdate,
)
from app.services import (
    activity_log_service,
    email_service,
    ledger_hooks,
    ledger_math,
    notification_preferences_service,
    settings_service,
)
from app.services.inventory_service import adjust_stock
from app.services.line_items import fetch_line_items, insert_line_items, replace_line_items, resolve_and_verify_lines
from app.services.master_data import lookup_bank_account_id, lookup_id_by_name
from app.services.party_service import get_latest_party_balance, get_party, require_party

LINE_ITEMS_TABLE = "invoice_line_items"
PARENT_COLUMN = "ledger_id"


class InvoiceNotFoundError(Exception):
    pass


class InvoiceNotDraftError(Exception):
    """Raised on a direct edit/finalize attempt against a finalized invoice —
    Section 5.1: finalized invoices are locked, only a Correction Entry can touch them."""


class InvoiceNotFinalizedError(Exception):
    """Raised when 'Fix This Invoice' is attempted against something still draft."""


class CreditLimitExceededError(Exception):
    """Section 16.1 — raised when finalizing would push the party's
    current_balance past their credit_limit and no override was given."""


class PaymentNotFoundError(Exception):
    """Raised when the given id doesn't refer to a recorded payment ('receiving' row)."""


def _line_out(row: dict) -> LineItemOut:
    return LineItemOut(
        id=row["id"],
        item_code=row["item_code"],
        qty=row["qty"],
        rate=float(row["rate"]),
        line_total=float(row["line_total"]),
        line_number=row["line_number"],
    )


def row_to_out(supabase: Client, row: dict) -> InvoiceOut:
    lines = fetch_line_items(supabase, LINE_ITEMS_TABLE, PARENT_COLUMN, row["id"])
    return InvoiceOut(
        id=row["id"],
        party_id=row["party_id"],
        invoice_no=row.get("invoice_no"),
        invoice_state=row["invoice_state"],
        correction_of=row.get("correction_of"),
        correction_reason=row.get("correction_reason"),
        payment_correction_of=row.get("payment_correction_of"),
        payment_correction_reason=row.get("payment_correction_reason"),
        due_date=row.get("due_date"),
        invoice_status=row["invoice_status"],
        txn_type=row["txn_type"],
        particular_id=row.get("particular_id"),
        bank_account_id=row.get("bank_account_id"),
        payment_reference=row.get("payment_reference"),
        payment_note=row.get("payment_note"),
        transaction_date=row["transaction_date"],
        discount_amount=float(row.get("discount_amount") or 0),
        total_amount=float(row["total_amount"]),
        received_at_sale=float(row.get("received_at_sale") or 0),
        previous_balance=float(row.get("previous_balance") or 0),
        current_balance=float(row["current_balance"]),
        approval_status=row["approval_status"],
        can_dispatch=row["approval_status"] == "approved",
        line_items=[_line_out(r) for r in lines],
        scan_slip_cloudinary_url=row.get("scan_slip_cloudinary_url"),
        created_at=row.get("created_at"),
    )


def fetch_invoice(supabase: Client, invoice_id: str) -> dict | None:
    resp = supabase.table("customer_ledgers").select("*").eq("id", invoice_id).limit(1).execute()
    return resp.data[0] if resp.data else None


def require_invoice(supabase: Client, invoice_id: str) -> dict:
    row = fetch_invoice(supabase, invoice_id)
    if row is None:
        raise InvoiceNotFoundError(f"Invoice '{invoice_id}' not found")
    return row


def fetch_invoice_by_number(supabase: Client, invoice_no: str) -> dict | None:
    """Section 9.1 Inbox matching rule (b): 'the subject line containing an
    invoice number the system recognizes.'"""
    resp = supabase.table("customer_ledgers").select("*").eq("invoice_no", invoice_no).limit(1).execute()
    return resp.data[0] if resp.data else None


def _existing_invoice_numbers(supabase: Client) -> list[str | None]:
    resp = supabase.table("customer_ledgers").select("invoice_no").execute()
    return [row.get("invoice_no") for row in resp.data]


# ── Draft Sale (Section 5.1: fully editable until finalized) ───────────────────


def create_draft_sale(supabase: Client, data: SaleDraftCreate) -> InvoiceOut:
    require_party(supabase, data.party_id)

    resolved_lines = resolve_and_verify_lines(supabase, data.line_items)
    total_amount = ledger_math.compute_invoice_total([line["line_total"] for line in resolved_lines], data.discount_amount)
    ledger_hooks.verify_invoice_math([line["line_total"] for line in resolved_lines], data.discount_amount, total_amount)

    previous_balance = get_latest_party_balance(supabase, data.party_id)
    current_balance = ledger_math.compute_sale_balance(previous_balance, total_amount)
    ledger_hooks.verify_balance(previous_balance, total_amount, "sale", current_balance)

    payload = {
        "party_id": data.party_id,
        "invoice_state": "draft",
        "invoice_status": "unpaid",
        "txn_type": "sale",
        "transaction_date": data.transaction_date.isoformat(),
        "discount_amount": str(data.discount_amount),
        "total_amount": str(total_amount),
        "received_at_sale": str(data.received_at_sale),
        "previous_balance": str(previous_balance),
        "current_balance": str(current_balance),
        "approval_status": "approved",  # gate decision happens at finalize, Section 7.4
        "scan_slip_cloudinary_url": data.scan_slip_cloudinary_url,
    }
    resp = supabase.table("customer_ledgers").insert(payload).execute()
    invoice_id = resp.data[0]["id"]
    insert_line_items(supabase, LINE_ITEMS_TABLE, PARENT_COLUMN, invoice_id, resolved_lines)
    return row_to_out(supabase, fetch_invoice(supabase, invoice_id))


def update_draft(supabase: Client, invoice_id: str, data: SaleDraftUpdate) -> InvoiceOut:
    invoice = require_invoice(supabase, invoice_id)
    if invoice["invoice_state"] != "draft":
        raise InvoiceNotDraftError(
            "This invoice is finalized and can't be edited directly — use Fix This Invoice instead (Section 5.1)"
        )

    if data.line_items is not None:
        resolved_lines = resolve_and_verify_lines(supabase, data.line_items)
    else:
        resolved_lines = fetch_line_items(supabase, LINE_ITEMS_TABLE, PARENT_COLUMN, invoice_id)

    discount_amount = data.discount_amount if data.discount_amount is not None else float(invoice["discount_amount"])
    line_totals = [line["line_total"] for line in resolved_lines]
    total_amount = ledger_math.compute_invoice_total(line_totals, discount_amount)
    ledger_hooks.verify_invoice_math(line_totals, discount_amount, total_amount)

    previous_balance = float(invoice["previous_balance"])
    current_balance = ledger_math.compute_sale_balance(previous_balance, total_amount)
    ledger_hooks.verify_balance(previous_balance, total_amount, "sale", current_balance)

    payload = {
        "discount_amount": str(discount_amount),
        "total_amount": str(total_amount),
        "current_balance": str(current_balance),
    }
    if data.transaction_date is not None:
        payload["transaction_date"] = data.transaction_date.isoformat()
    if data.received_at_sale is not None:
        payload["received_at_sale"] = str(data.received_at_sale)
    if data.scan_slip_cloudinary_url is not None:
        payload["scan_slip_cloudinary_url"] = data.scan_slip_cloudinary_url

    supabase.table("customer_ledgers").update(payload).eq("id", invoice_id).execute()
    if data.line_items is not None:
        replace_line_items(supabase, LINE_ITEMS_TABLE, PARENT_COLUMN, invoice_id, resolved_lines)

    return row_to_out(supabase, fetch_invoice(supabase, invoice_id))


# ── Finalize (Section 5.1, 5.3, 7.4 Human Gate) ─────────────────────────────────


def finalize_invoice(
    supabase: Client,
    invoice_id: str,
    today: date | None = None,
    *,
    user: dict | None = None,
    override_credit_limit: bool = False,
) -> InvoiceOut:
    invoice = require_invoice(supabase, invoice_id)
    if invoice["invoice_state"] != "draft":
        raise InvoiceNotDraftError("Only a draft invoice can be finalized")

    today = today or date.today()
    total_amount = float(invoice["total_amount"])

    # Section 16.1 — Credit Limit Enforcement. Checked before anything else
    # changes (stock, invoice_no) so a blocked finalize is a true no-op.
    party = get_party(supabase, invoice["party_id"])
    credit_limit = float(party["credit_limit"]) if party and party.get("credit_limit") is not None else None
    current_balance = float(invoice["current_balance"])
    if credit_limit is not None and current_balance > credit_limit:
        excess = current_balance - credit_limit
        if not override_credit_limit:
            raise CreditLimitExceededError(
                f"This exceeds {party['party_name']}'s credit limit of Rs. {credit_limit:,.2f} by Rs. {excess:,.2f}."
            )
        if user is not None:
            activity_log_service.log_activity(
                supabase,
                user["id"],
                "credit_override",
                f"Overrode {party['party_name']}'s credit limit of Rs. {credit_limit:,.2f} "
                f"(exceeded by Rs. {excess:,.2f}) to finalize a Rs. {total_amount:,.2f} invoice",
            )

    invoice_no = ledger_math.next_sequence_number(_existing_invoice_numbers(supabase))
    txn_date = date.fromisoformat(invoice["transaction_date"]) if isinstance(invoice["transaction_date"], str) else invoice["transaction_date"]
    due_date = ledger_math.compute_due_date(txn_date)
    invoice_status = ledger_math.compute_invoice_status(total_amount, invoice.get("received_at_sale") or 0, due_date, today)

    threshold = settings_service.get_human_gate_threshold(supabase)
    approval_status = "pending" if ledger_math.is_above_human_gate(total_amount, threshold) else "approved"

    lines = fetch_line_items(supabase, LINE_ITEMS_TABLE, PARENT_COLUMN, invoice_id)
    for line in lines:
        adjust_stock(supabase, line["item_code"], -line["qty"])

    payload = {
        "invoice_state": "finalized",
        "invoice_no": invoice_no,
        "due_date": due_date.isoformat(),
        "invoice_status": invoice_status,
        "approval_status": approval_status,
    }
    supabase.table("customer_ledgers").update(payload).eq("id", invoice_id).execute()

    if approval_status == "pending":
        _notify_admins_of_pending_invoice(supabase, invoice_no, total_amount)

    return row_to_out(supabase, fetch_invoice(supabase, invoice_id))


def _notify_admins_of_pending_invoice(supabase: Client, invoice_no: str, total_amount: float) -> None:
    """Section 7.4 Human Gate — no notification existed for this at all before
    (unlike the Login Approval Gate's own admin alert, Section 3.1); an Admin
    previously only found out an invoice needed approval by opening the Human
    Gate Drawer. Gated per-admin by Section 10's human_gate_approval preference
    (default on), same pattern as auth.py's login-request notification."""
    admins = supabase.table("users").select("id, email").eq("role", "admin").eq("is_active", True).execute()
    for admin in admins.data:
        if not notification_preferences_service.get_preferences(supabase, admin["id"]).human_gate_approval:
            continue
        try:
            email_service.send_human_gate_pending_notification(admin["email"], invoice_no, total_amount)
        except email_service.EmailDispatchError:
            pass  # best-effort — Gmail creds may still be a placeholder; finalize must not fail because of this


def approve_invoice(supabase: Client, invoice_id: str) -> InvoiceOut:
    """Section 7.4 Human Gate Drawer — Admin APPROVE."""
    require_invoice(supabase, invoice_id)
    supabase.table("customer_ledgers").update({"approval_status": "approved"}).eq("id", invoice_id).execute()
    return row_to_out(supabase, fetch_invoice(supabase, invoice_id))


def reject_invoice(supabase: Client, invoice_id: str) -> InvoiceOut:
    """Section 7.4 Human Gate Drawer — Admin REJECT."""
    require_invoice(supabase, invoice_id)
    supabase.table("customer_ledgers").update({"approval_status": "rejected"}).eq("id", invoice_id).execute()
    return row_to_out(supabase, fetch_invoice(supabase, invoice_id))


# ── Record Payment (Section 5.0 — the other half of the ledger) ────────────────


def record_payment(supabase: Client, data: RecordPaymentCreate) -> InvoiceOut:
    require_party(supabase, data.party_id)
    particular_id = lookup_id_by_name(supabase, "particulars", data.method)
    bank_account_id = lookup_bank_account_id(supabase, data.bank_name) if data.bank_name else None

    total_amount = ledger_math.round2(data.amount)
    previous_balance = get_latest_party_balance(supabase, data.party_id)
    current_balance = ledger_math.compute_receiving_balance(previous_balance, total_amount)
    ledger_hooks.verify_balance(previous_balance, total_amount, "receiving", current_balance)

    payload = {
        "party_id": data.party_id,
        "invoice_state": "finalized",  # a payment is a completed, immediate action — never a draft
        "invoice_status": "paid",
        "txn_type": "receiving",
        "particular_id": particular_id,
        "bank_account_id": bank_account_id,
        "payment_reference": data.payment_reference,
        "payment_note": data.payment_note,
        "transaction_date": data.transaction_date.isoformat(),
        "discount_amount": "0",
        "total_amount": str(total_amount),
        "previous_balance": str(previous_balance),
        "current_balance": str(current_balance),
        # Section 12.1: "A recorded payment never triggers the Human Gate ... even
        # if the amount exceeds Rs. 100,000" — always pre-approved.
        "approval_status": "approved",
    }
    resp = supabase.table("customer_ledgers").insert(payload).execute()
    # A 'receiving' row has zero invoice_line_items rows (Section 5's note).
    return row_to_out(supabase, fetch_invoice(supabase, resp.data[0]["id"]))


# ── Correction Entry / "Fix This Invoice" (Section 5.1) ─────────────────────────


def create_correction(supabase: Client, invoice_id: str, data: CorrectionCreate) -> InvoiceOut:
    original = require_invoice(supabase, invoice_id)
    if original["invoice_state"] != "finalized":
        raise InvoiceNotFinalizedError("Fix This Invoice only applies to a finalized invoice — a draft can be edited directly")

    if data.line_items is not None:
        resolved_lines = resolve_and_verify_lines(supabase, data.line_items)
    else:
        resolved_lines = fetch_line_items(supabase, LINE_ITEMS_TABLE, PARENT_COLUMN, invoice_id)

    discount_amount = data.discount_amount if data.discount_amount is not None else float(original["discount_amount"])
    line_totals = [line["line_total"] for line in resolved_lines]
    corrected_total = ledger_math.compute_invoice_total(line_totals, discount_amount)
    ledger_hooks.verify_invoice_math(line_totals, discount_amount, corrected_total)

    delta = ledger_math.round2(corrected_total - ledger_math.round2(original["total_amount"]))

    previous_balance = get_latest_party_balance(supabase, original["party_id"])
    current_balance = ledger_math.compute_correction_balance(previous_balance, delta)
    ledger_hooks.verify_correction_balance(previous_balance, delta, current_balance)

    payload = {
        "party_id": original["party_id"],
        "invoice_state": "finalized",  # a correction is itself a final record — never a draft
        "invoice_status": "unpaid",
        "txn_type": "sale" if delta >= 0 else "receiving",  # sign of the delta drives the direction
        "correction_of": invoice_id,
        "correction_reason": data.reason,
        "transaction_date": date.today().isoformat(),
        "discount_amount": "0",
        "total_amount": str(abs(delta)),
        "previous_balance": str(previous_balance),
        "current_balance": str(current_balance),
        "approval_status": "approved",
    }
    resp = supabase.table("customer_ledgers").insert(payload).execute()
    # The Correction Entry itself doesn't get its own invoice_line_items rows —
    # its total_amount is the signed delta; correction_reason plus the original's
    # (unchanged) line items are the record of what it corrects. See
    # schema_phase2.sql's design-decision note #4.
    return row_to_out(supabase, fetch_invoice(supabase, resp.data[0]["id"]))


# ── Payment Correction / "Fix This Payment" (Section 16.6) ──────────────────────


def create_payment_correction(
    supabase: Client, payment_id: str, data: PaymentCorrectionCreate, user_id: str
) -> InvoiceOut:
    """Mirrors create_correction's shape exactly, but for a recorded payment
    ('receiving' row) instead of a sale. Never mutates the original payment —
    inserts a signed-delta row referencing it instead.

    Sign convention (opposite of create_correction's, since a payment reduces
    the balance rather than increasing it): delta = original_amount −
    corrected_amount. A corrected_amount LOWER than what was recorded means
    the party actually paid less than credited, so the balance should go back
    UP by that difference — delta is positive, and compute_correction_balance
    adds it straight onto previous_balance, same formula create_correction uses.
    """
    original = require_invoice(supabase, payment_id)
    if original["txn_type"] != "receiving":
        raise PaymentNotFoundError(f"'{payment_id}' is not a recorded payment")

    original_amount = ledger_math.round2(original["total_amount"])
    corrected_amount = ledger_math.round2(data.corrected_amount) if data.corrected_amount is not None else original_amount
    delta = ledger_math.round2(original_amount - corrected_amount)

    previous_balance = get_latest_party_balance(supabase, original["party_id"])
    current_balance = ledger_math.compute_correction_balance(previous_balance, delta)
    ledger_hooks.verify_correction_balance(previous_balance, delta, current_balance)

    note_parts = [data.reason]
    if data.corrected_amount is not None:
        note_parts.append(f"Amount corrected from Rs. {original_amount:,.2f} to Rs. {corrected_amount:,.2f}")
    if data.corrected_method is not None:
        note_parts.append(f"Method corrected to {data.corrected_method}")
    if data.corrected_date is not None:
        note_parts.append(f"Date corrected to {data.corrected_date.isoformat()}")

    payload = {
        "party_id": original["party_id"],
        "invoice_state": "finalized",  # a correction is itself a final record — never a draft
        "invoice_status": "unpaid",
        "txn_type": "sale" if delta >= 0 else "receiving",  # sign of the delta drives the direction
        "payment_correction_of": payment_id,
        "payment_correction_reason": data.reason,
        "payment_note": " — ".join(note_parts),
        "transaction_date": date.today().isoformat(),
        "discount_amount": "0",
        "total_amount": str(abs(delta)),
        "previous_balance": str(previous_balance),
        "current_balance": str(current_balance),
        "approval_status": "approved",
    }
    resp = supabase.table("customer_ledgers").insert(payload).execute()
    activity_log_service.log_activity(
        supabase,
        user_id,
        "payment_correction",
        f"Corrected a Rs. {original_amount:,.2f} payment: {data.reason}",
    )
    return row_to_out(supabase, fetch_invoice(supabase, resp.data[0]["id"]))


# ── Party Ledger read (Section 5.2: newest first, default) ─────────────────────


def list_party_ledger(supabase: Client, party_id: str) -> list[InvoiceOut]:
    resp = (
        supabase.table("customer_ledgers")
        .select("*")
        .eq("party_id", party_id)
        .is_("deleted_at", "null")
        .order("transaction_date", desc=True)
        .order("created_at", desc=True)
        .execute()
    )
    return [row_to_out(supabase, row) for row in resp.data]


# ── Invoices list (Screen 6, and the Dashboard's stats strip) ──────────────────


def list_invoices(supabase: Client) -> list[InvoiceOut]:
    """Every 'sale' row across all parties, newest first — a 'receiving' (payment)
    row never appears here, same distinction Section 5.4.D draws on the real
    system's separate Sale vs. Payment lists."""
    resp = (
        supabase.table("customer_ledgers")
        .select("*")
        .eq("txn_type", "sale")
        .is_("deleted_at", "null")
        .order("transaction_date", desc=True)
        .order("created_at", desc=True)
        .execute()
    )
    return [row_to_out(supabase, row) for row in resp.data]
