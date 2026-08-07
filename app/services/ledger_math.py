"""Pure formulas — Sections 2.2, 5.0, 5.1, 5.3, 5.4.B. No I/O, no DB, no FastAPI.

Kept separate so Section 12.0 layer-1 unit tests can prove these are right in
isolation; app/services/ledger_hooks.py re-runs them as a write-time check
(Section 7.3), and the *_service.py modules call them to compute what actually
gets written.
"""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

TWO_PLACES = Decimal("0.01")


def _d(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def round2(value) -> Decimal:
    return _d(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def compute_line_total(rate, qty) -> Decimal:
    """Section 5 (invoice_line_items): line_total == rate * qty, per line item.
    This is Section 7.3's bare math_formula, now applied per line rather than
    once per invoice — an invoice can hold many of these (the multi-item fix)."""
    return round2(_d(rate) * _d(qty))


def compute_invoice_total(line_totals: list, discount_amount=0) -> Decimal:
    """Section 5 header rule: total_amount == SUM(invoice_line_items.line_total)
    − discount_amount. discount_amount applies once per invoice (Section 2.3's
    single 'Special Discount' field), not per line."""
    total = sum((_d(x) for x in line_totals), start=Decimal("0"))
    return round2(total - _d(discount_amount))


def compute_sale_balance(previous_balance, total_amount) -> Decimal:
    """Section 5.0 formula, 'sale' branch: current_balance = previous_balance + total_amount."""
    return round2(_d(previous_balance) + _d(total_amount))


def compute_receiving_balance(previous_balance, total_amount) -> Decimal:
    """Section 5.0 formula, 'receiving' branch: current_balance = previous_balance − total_amount."""
    return round2(_d(previous_balance) - _d(total_amount))


def compute_ledger_balance(previous_balance, total_amount, txn_type: str) -> Decimal:
    if txn_type == "sale":
        return compute_sale_balance(previous_balance, total_amount)
    if txn_type == "receiving":
        return compute_receiving_balance(previous_balance, total_amount)
    raise ValueError(f"Unknown txn_type '{txn_type}'")


def compute_correction_balance(previous_balance, delta_amount) -> Decimal:
    """Section 5.1: a correction's total_amount is a signed delta (negative =
    Credit Note, positive = Debit Note) applied directly to the balance chain."""
    return round2(_d(previous_balance) + _d(delta_amount))


def compute_purchase_balance(previous_balance, total_amount) -> Decimal:
    """Section 5.4.B: 'same balance-chain discipline ... from the business's side
    as the buyer' — every purchases row increases what we owe that supplier."""
    return round2(_d(previous_balance) + _d(total_amount))


def next_sequence_number(existing_numbers: list[str | None], start_at: int = 1) -> str:
    """Section 5.3: invoice_no = MAX(invoice_no::int)+1. Also used for
    purchase_bill_no (Section 5.4.B: 'same rule as Section 5.3's invoice numbering').

    Empty-table edge case (not covered by the PRD's raw MAX()+1 SQL, which would
    be NULL+1 = NULL): starts the sequence at `start_at` instead.
    """
    numeric = [int(n) for n in existing_numbers if n]
    if not numeric:
        return str(start_at)
    return str(max(numeric) + 1)


def compute_due_date(transaction_date: date, days: int = 15) -> date:
    """Section 5.3: defaults to transaction_date + 15 days ('Pay Dues within 15 Days')."""
    return transaction_date + timedelta(days=days)


def compute_invoice_status(total_amount, received_at_sale, due_date: date | None, today: date) -> str:
    """Section 5.3 status rules, using only fields that live directly on this
    invoice's own row (received_at_sale) — see schema_phase2.sql's design-decision
    note #3 on why a later 'Record Payment' isn't linked to a specific invoice."""
    total = _d(total_amount)
    received = _d(received_at_sale)

    if received <= 0:
        base_status = "unpaid"
    elif received >= total:
        base_status = "paid"
    else:
        base_status = "partial"

    if base_status in ("unpaid", "partial") and due_date is not None and today > due_date:
        return "overdue"
    return base_status


def replay_ledger(starting_balance, rows: list[tuple[str, object]]) -> list[Decimal]:
    """Applies compute_ledger_balance across a sequence of (txn_type, amount)
    rows in append order, returning each resulting current_balance. Used both by
    the golden-replay test (Section 12.1) and available for any future
    consistency check that needs to recompute a party's whole chain from scratch."""
    balances: list[Decimal] = []
    balance = _d(starting_balance)
    for txn_type, amount in rows:
        balance = compute_ledger_balance(balance, amount, txn_type)
        balances.append(balance)
    return balances


def is_above_human_gate(total_amount, threshold) -> bool:
    """Section 7.4 gate_trigger: if bill_total > threshold -> Human Gate."""
    return _d(total_amount) > _d(threshold)
