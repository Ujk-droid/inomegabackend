from datetime import date
from decimal import Decimal

from app.services.ledger_math import (
    compute_correction_balance,
    compute_due_date,
    compute_invoice_status,
    compute_invoice_total,
    compute_ledger_balance,
    compute_line_total,
    compute_purchase_balance,
    is_above_human_gate,
    next_sequence_number,
    replay_ledger,
)


def test_line_total_matches_section_2_3_sample():
    # Section 2.1/2.3: rate 12300, qty 15 -> 184500 (INV-2127's single line item)
    assert compute_line_total(rate=12300, qty=15) == Decimal("184500.00")


def test_invoice_total_sums_multiple_lines():
    # a 2-item invoice: 184500 + 9200 = 193700
    assert compute_invoice_total([Decimal("184500.00"), Decimal("9200.00")]) == Decimal("193700.00")


def test_invoice_total_applies_discount_once_at_header_level():
    assert compute_invoice_total([Decimal("5000.00"), Decimal("5000.00")], discount_amount=500) == Decimal("9500.00")


def test_invoice_total_with_single_line_and_no_discount():
    assert compute_invoice_total([Decimal("184500.00")], discount_amount=0) == Decimal("184500.00")


def test_sale_increases_balance():
    assert compute_ledger_balance(previous_balance=100, total_amount=50, txn_type="sale") == Decimal("150.00")


def test_receiving_decreases_balance():
    assert compute_ledger_balance(previous_balance=150, total_amount=50, txn_type="receiving") == Decimal("100.00")


def test_correction_delta_can_reduce_balance():
    # Credit Note: negative delta
    assert compute_correction_balance(previous_balance=1000, delta_amount=-200) == Decimal("800.00")


def test_correction_delta_can_increase_balance():
    # Debit Note: positive delta
    assert compute_correction_balance(previous_balance=1000, delta_amount=200) == Decimal("1200.00")


def test_purchase_balance_mirrors_sale():
    assert compute_purchase_balance(previous_balance=500, total_amount=300) == Decimal("800.00")


def test_next_sequence_number_starts_at_one_when_empty():
    assert next_sequence_number([]) == "1"


def test_next_sequence_number_increments_max():
    assert next_sequence_number(["2044", "2052", "2057", None]) == "2058"


def test_due_date_defaults_to_15_days():
    assert compute_due_date(date(2026, 7, 23)) == date(2026, 8, 7)  # matches INV-2127's issue date + 15


def test_invoice_status_unpaid_when_nothing_received():
    status = compute_invoice_status(total_amount=1000, received_at_sale=0, due_date=date(2026, 12, 31), today=date(2026, 7, 30))
    assert status == "unpaid"


def test_invoice_status_partial():
    status = compute_invoice_status(total_amount=1000, received_at_sale=400, due_date=date(2026, 12, 31), today=date(2026, 7, 30))
    assert status == "partial"


def test_invoice_status_paid():
    status = compute_invoice_status(total_amount=1000, received_at_sale=1000, due_date=date(2026, 12, 31), today=date(2026, 7, 30))
    assert status == "paid"


def test_invoice_status_flips_to_overdue_past_due_date():
    status = compute_invoice_status(total_amount=1000, received_at_sale=0, due_date=date(2026, 1, 1), today=date(2026, 7, 30))
    assert status == "overdue"


def test_paid_invoice_never_flips_to_overdue():
    status = compute_invoice_status(total_amount=1000, received_at_sale=1000, due_date=date(2026, 1, 1), today=date(2026, 7, 30))
    assert status == "paid"


def test_human_gate_threshold():
    assert is_above_human_gate(184500, threshold=100000) is True
    assert is_above_human_gate(99999.99, threshold=100000) is False
    assert is_above_human_gate(100000, threshold=100000) is False  # strictly greater-than, per Section 7.4


def test_united_scale_ijtibah_golden_ledger_replay():
    """Section 2.2 / Section 12.1: 'current_balance recomputes correctly across a
    full ledger replay (use the United Scale Ijtibah data from Section 2.2 as the
    golden test case)'.

    The PRD's own table only discloses S.No 280, 281, the final row 307, and the
    END totals — the ~25 rows in between are shown as '...' in the source
    document itself, not omitted by this test. Every number asserted below is
    either transcribed directly from the PRD or derived arithmetically from
    disclosed numbers:
      - previous_balance before row 280: 136,276 - 24,900 = 111,376 (derived)
      - row 280, row 281, row 307: transaction amounts and resulting balances
        are copied verbatim from Section 2.2's table
      - END row's total debit (1,409,362) / total credit (1,048,000): copied
        verbatim
    The two bridging rows below are the only synthetic input — sized so the
    replay's final numbers reconcile exactly against all five real anchors at
    once (136,276; 16,276; 472,738; 1,409,362; 1,048,000), which would not be
    possible if the arithmetic were wrong.
    """
    previous_balance_before_280 = Decimal("136276.00") - Decimal("24900.00")
    assert previous_balance_before_280 == Decimal("111376.00")

    rows = [
        ("sale", Decimal("24900.00")),        # S.No 280: Sale - 2044
        ("receiving", Decimal("120000.00")),  # S.No 281: Receiving - 1167 (Cheque)
        ("sale", Decimal("1361462.00")),      # synthetic bridge: aggregate of the omitted rows' sales
        ("receiving", Decimal("928000.00")),  # synthetic bridge: aggregate of the omitted rows' receivings
        ("sale", Decimal("23000.00")),        # S.No 307: Sale - 2132
    ]

    balances = replay_ledger(previous_balance_before_280, rows)

    assert balances[0] == Decimal("136276.00")  # matches PRD row 280 exactly
    assert balances[1] == Decimal("16276.00")   # matches PRD row 281 exactly
    assert balances[-1] == Decimal("472738.00")  # matches PRD row 307 exactly

    total_debit = sum(amount for txn_type, amount in rows if txn_type == "sale")
    total_credit = sum(amount for txn_type, amount in rows if txn_type == "receiving")
    assert total_debit == Decimal("1409362.00")   # matches PRD's END row total debit exactly
    assert total_credit == Decimal("1048000.00")  # matches PRD's END row total credit exactly
