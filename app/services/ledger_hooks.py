"""Section 7.3 — Harness Verify, applied at the application layer.

The PRD's harness section describes this as a Claude-Code PostToolUse hook that
re-validates the math/balance formulas after every ledger write during *development*
(when Claude Code itself is the one editing/writing). For the *running* app, the
equivalent maker-checker discipline (Section 7.1: "the invoice-generation agent
(maker) is checked by a separate validation step (checker) before any email is
sent") is implemented here instead: every ledger/invoice/purchase write in
ledger_service.py and purchase_service.py calls these functions immediately
before the insert, independently recomputing the two formulas and comparing
them to what's about to be written. A mismatch blocks the write and appends a
line to progress.md — this can only happen from a bug in this codebase's own
computation (callers never take total_amount/current_balance as untrusted input),
but the check stays as real defense-in-depth, exactly as Section 7.3 asks for.
"""

from datetime import datetime, timezone
from pathlib import Path

from app.services import ledger_math

PROGRESS_FILE = Path(__file__).resolve().parent.parent.parent / "progress.md"


class LedgerIntegrityError(Exception):
    """Raised when a write's total_amount or current_balance doesn't match what
    the formulas say it should be. Must block the write, never proceed anyway."""


def _log_violation(message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    line = f"- [{timestamp}] HARNESS VIOLATION BLOCKED: {message}\n"
    try:
        with open(PROGRESS_FILE, "a") as f:
            f.write(line)
    except OSError:
        pass  # logging must never be the reason a blocking check fails to block


def verify_line_math(rate, qty, line_total) -> None:
    """Section 7.3 math_formula, applied per invoice_line_items row."""
    expected = ledger_math.compute_line_total(rate, qty)
    actual = ledger_math.round2(line_total)
    if expected != actual:
        message = f"math_formula (line) failed: expected line_total={expected} (rate={rate}, qty={qty}), got {actual}"
        _log_violation(message)
        raise LedgerIntegrityError(message)


def verify_invoice_math(line_totals, discount_amount, total_amount) -> None:
    """Section 7.3 math_formula, extended to the header: total_amount ==
    SUM(line_totals) − discount_amount (Section 12.1 requires discount to be
    reflected in total_amount)."""
    expected = ledger_math.compute_invoice_total(line_totals, discount_amount)
    actual = ledger_math.round2(total_amount)
    if expected != actual:
        message = (
            f"math_formula (invoice) failed: expected total_amount={expected} "
            f"(sum(line_totals)={sum(line_totals)}, discount={discount_amount}), got {actual}"
        )
        _log_violation(message)
        raise LedgerIntegrityError(message)


def verify_balance(previous_balance, total_amount, txn_type, current_balance) -> None:
    """Section 7.3: current_balance == previous_balance + total_amount (signed by txn_type)."""
    expected = ledger_math.compute_ledger_balance(previous_balance, total_amount, txn_type)
    actual = ledger_math.round2(current_balance)
    if expected != actual:
        message = (
            f"balance_formula failed: expected current_balance={expected} "
            f"(previous_balance={previous_balance}, total_amount={total_amount}, txn_type={txn_type}), got {actual}"
        )
        _log_violation(message)
        raise LedgerIntegrityError(message)


def verify_correction_balance(previous_balance, delta_amount, current_balance) -> None:
    expected = ledger_math.compute_correction_balance(previous_balance, delta_amount)
    actual = ledger_math.round2(current_balance)
    if expected != actual:
        message = (
            f"balance_formula (correction) failed: expected current_balance={expected} "
            f"(previous_balance={previous_balance}, delta_amount={delta_amount}), got {actual}"
        )
        _log_violation(message)
        raise LedgerIntegrityError(message)


def verify_purchase_balance(previous_balance, total_amount, current_balance) -> None:
    expected = ledger_math.compute_purchase_balance(previous_balance, total_amount)
    actual = ledger_math.round2(current_balance)
    if expected != actual:
        message = (
            f"purchase balance_formula failed: expected current_balance={expected} "
            f"(previous_balance={previous_balance}, total_amount={total_amount}), got {actual}"
        )
        _log_violation(message)
        raise LedgerIntegrityError(message)
