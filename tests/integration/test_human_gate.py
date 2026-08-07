"""Section 13.0 Phase 2 exit test: 'Invoice #2127 (Rs. 184,500, Section 2.3) is
proven to trigger the Human Gate and a sub-threshold invoice is proven not to.'
Also Section 12.1: a recorded payment never triggers the gate, even above threshold.
"""


def _finalize_sale(client, party_id, item_code, qty, rate):
    created = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": qty, "rate": rate}],
            "transaction_date": "2026-07-23",
        },
    ).json()
    return client.post(f"/api/v1/invoices/{created['id']}/finalize").json()


def test_invoice_2127_rs_184500_triggers_human_gate(client, party_id, item_code):
    # Section 2.1/2.3: rate 12300, qty 15 -> 184,500 — the PRD's live test case,
    # which exceeds the Rs. 100,000 threshold (AGENT_HUMAN_GATE_THRESHOLD).
    invoice = _finalize_sale(client, party_id, item_code, qty=15, rate=12300)

    assert invoice["total_amount"] == 184500
    assert invoice["approval_status"] == "pending"
    assert invoice["can_dispatch"] is False  # dispatch halted until Admin approves (Section 7.4)


def test_sub_threshold_invoice_does_not_trigger_human_gate(client, party_id, item_code):
    invoice = _finalize_sale(client, party_id, item_code, qty=5, rate=12300)  # 61,500 — under threshold

    assert invoice["total_amount"] == 61500
    assert invoice["approval_status"] == "approved"
    assert invoice["can_dispatch"] is True


def test_invoice_exactly_at_threshold_does_not_trigger_gate(client, party_id, item_code):
    # Section 7.4: "If bill_total > 100,000" — strictly greater than, so exactly
    # 100,000 must NOT gate.
    invoice = _finalize_sale(client, party_id, item_code, qty=1, rate=100000)

    assert invoice["total_amount"] == 100000
    assert invoice["approval_status"] == "approved"
    assert invoice["can_dispatch"] is True


def test_multi_item_invoice_above_threshold_triggers_gate(client, party_id, item_code):
    # New: the gate must check the invoice HEADER total (sum of all lines minus
    # discount), not any single line item's amount.
    second_item = client.post(
        "/api/v1/inventory/create",
        data={"item_code": "LC-500KG", "item_name": "Load Cell 500Kg", "unit": "pcs", "rate": "4500", "quantity_in_stock": "50"},
    ).json()["item_code"]

    created = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [
                {"item_code": item_code, "qty": 6, "rate": 12300},   # 73,800 — under threshold alone
                {"item_code": second_item, "qty": 6, "rate": 4500},  # 27,000 — under threshold alone
            ],
            "transaction_date": "2026-07-23",
        },
    ).json()

    invoice = client.post(f"/api/v1/invoices/{created['id']}/finalize").json()
    assert invoice["total_amount"] == 100800  # 73800 + 27000, over threshold combined
    assert invoice["approval_status"] == "pending"
    assert invoice["can_dispatch"] is False


def test_admin_can_approve_a_gated_invoice(client, party_id, item_code):
    invoice = _finalize_sale(client, party_id, item_code, qty=15, rate=12300)
    assert invoice["approval_status"] == "pending"

    resp = client.post(f"/api/v1/invoices/{invoice['id']}/approve")
    assert resp.status_code == 200
    body = resp.json()
    assert body["approval_status"] == "approved"
    assert body["can_dispatch"] is True


def test_admin_can_reject_a_gated_invoice(client, party_id, item_code):
    invoice = _finalize_sale(client, party_id, item_code, qty=15, rate=12300)

    resp = client.post(f"/api/v1/invoices/{invoice['id']}/reject")
    assert resp.status_code == 200
    body = resp.json()
    assert body["approval_status"] == "rejected"
    assert body["can_dispatch"] is False


def test_large_payment_never_triggers_human_gate(client, party_id, item_code):
    # Section 12.1: "A recorded payment never triggers the Human Gate ... even if
    # the amount exceeds Rs. 100,000"
    resp = client.post(
        "/api/v1/invoices/payments",
        json={
            "party_id": party_id,
            "amount": 500000,
            "method": "Bank Transfer",
            "bank_name": "Meezan Bank",
            "transaction_date": "2026-07-30",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["approval_status"] == "approved"
    assert body["can_dispatch"] is True
