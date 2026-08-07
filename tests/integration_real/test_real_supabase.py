"""Phase 1 + Phase 2 acceptance criteria (PRD Section 12.1), replayed against
the REAL Supabase project instead of tests/fake_supabase.py's in-memory
stand-in (tests/integration/*). Confirms the schema.sql + schema_phase2.sql
DDL, FK constraints, and enum types actually match what app/services/* expects
when talking to real Postgres/PostgREST rather than the fake client.

Reference-table lookups used below (unit 'pcs', particulars 'Cash' and 'Bank
Transfer', bank_account 'Cash Received', categories_1 left unset) are all
already seeded by db/schema.sql's own `INSERT ... ON CONFLICT DO NOTHING`
block — nothing new is added to those master tables by this suite.

Every party/item this suite creates is prefixed with a run-unique ZZTEST_
marker and is deleted by the `real_env` fixture's teardown (tests/integration_real/conftest.py),
in FK-safe order, whether or not the tests pass.
"""

import pytest


@pytest.fixture(scope="module")
def seeded(real_env, run_id):
    client, created = real_env

    party = client.post(
        "/api/v1/parties",
        json={"party_name": f"ZZTEST_Party_{run_id}", "party_type": "customer"},
    )
    assert party.status_code == 201, party.text
    party_id = party.json()["id"]
    created["party_ids"].append(party_id)

    supplier = client.post(
        "/api/v1/parties",
        json={"party_name": f"ZZTEST_Supplier_{run_id}", "party_type": "supplier"},
    )
    assert supplier.status_code == 201, supplier.text
    supplier_id = supplier.json()["id"]
    created["party_ids"].append(supplier_id)

    item = client.post(
        "/api/v1/inventory/create",
        data={
            "item_code": f"ZZTEST-{run_id}-A",
            "item_name": "ZZTEST Platform Scale A",
            "unit": "pcs",
            "rate": "12300",
            "quantity_in_stock": "100",
        },
    )
    assert item.status_code == 201, item.text
    item_code = item.json()["item_code"]
    created["item_codes"].append(item_code)

    item2 = client.post(
        "/api/v1/inventory/create",
        data={
            "item_code": f"ZZTEST-{run_id}-B",
            "item_name": "ZZTEST Load Cell B",
            "unit": "pcs",
            "rate": "4500",
            "quantity_in_stock": "50",
        },
    )
    assert item2.status_code == 201, item2.text
    item_code_2 = item2.json()["item_code"]
    created["item_codes"].append(item_code_2)

    return {
        "party_id": party_id,
        "supplier_id": supplier_id,
        "item_code": item_code,
        "item_code_2": item_code_2,
    }


def test_inventory_create_and_get_real(real_env, seeded):
    client, _ = real_env
    resp = client.get(f"/api/v1/inventory/{seeded['item_code']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["rate"] == 12300
    assert body["quantity_in_stock"] == 100
    assert body["unit"] == "pcs"
    assert body["is_low_stock"] is False


def test_party_create_and_zero_balance_real(real_env, seeded):
    client, _ = real_env
    resp = client.get(f"/api/v1/parties/{seeded['party_id']}/balance")
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_balance"] == 0.0


def test_duplicate_party_name_rejected_real(real_env, seeded, run_id):
    client, _ = real_env
    resp = client.post(
        "/api/v1/parties",
        json={"party_name": f"ZZTEST_Party_{run_id}", "party_type": "customer"},
    )
    assert resp.status_code == 409


def test_invoice_2127_style_multi_item_triggers_human_gate_real(real_env, seeded):
    """Reproduces PRD Section 2.3's INV-2127 live test case (qty 15 x rate
    12300 = 184,500, over the Rs. 100,000 threshold) but as a two-line invoice
    so the gate is proven to check the header total, not a single line."""
    client, _ = real_env

    draft = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": seeded["party_id"],
            "line_items": [
                {"item_code": seeded["item_code"], "qty": 10, "rate": 12300},  # 123,000
                {"item_code": seeded["item_code_2"], "qty": 5, "rate": 4500},  # 22,500
            ],
            "transaction_date": "2026-07-23",
        },
    )
    assert draft.status_code == 201, draft.text
    invoice_id = draft.json()["id"]

    finalized = client.post(f"/api/v1/invoices/{invoice_id}/finalize")
    assert finalized.status_code == 200, finalized.text
    body = finalized.json()

    assert body["total_amount"] == 145500  # 123000 + 22500
    assert body["current_balance"] == 145500  # previous_balance was 0
    assert body["approval_status"] == "pending"
    assert body["can_dispatch"] is False
    assert body["invoice_no"] is not None
    assert len(body["line_items"]) == 2

    approved = client.post(f"/api/v1/invoices/{invoice_id}/approve")
    assert approved.status_code == 200
    assert approved.json()["approval_status"] == "approved"
    assert approved.json()["can_dispatch"] is True


def test_sub_threshold_invoice_does_not_trigger_gate_real(real_env, seeded):
    client, _ = real_env

    draft = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": seeded["party_id"],
            "line_items": [{"item_code": seeded["item_code_2"], "qty": 4, "rate": 4500}],  # 18,000
            "transaction_date": "2026-07-24",
        },
    )
    assert draft.status_code == 201, draft.text
    invoice_id = draft.json()["id"]

    finalized = client.post(f"/api/v1/invoices/{invoice_id}/finalize")
    assert finalized.status_code == 200, finalized.text
    body = finalized.json()

    assert body["total_amount"] == 18000
    assert body["approval_status"] == "approved"
    assert body["can_dispatch"] is True
    # previous_balance carries forward from the prior (approved) invoice above
    assert body["previous_balance"] == 145500
    assert body["current_balance"] == 163500


def test_large_payment_never_triggers_gate_real(real_env, seeded):
    """PRD Section 12.1: a recorded payment never triggers the Human Gate,
    even above the threshold, and the running balance decreases (Credit)."""
    client, _ = real_env

    resp = client.post(
        "/api/v1/invoices/payments",
        json={
            "party_id": seeded["party_id"],
            "amount": 150000,
            "method": "Bank Transfer",
            "bank_name": "Cash Received",
            "transaction_date": "2026-07-25",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["approval_status"] == "approved"
    assert body["can_dispatch"] is True
    assert body["previous_balance"] == 163500
    assert body["current_balance"] == 13500  # 163500 - 150000


def test_multi_item_purchase_increases_stock_for_every_line_real(real_env, seeded):
    client, _ = real_env

    before_a = client.get(f"/api/v1/inventory/{seeded['item_code']}").json()["quantity_in_stock"]
    before_b = client.get(f"/api/v1/inventory/{seeded['item_code_2']}").json()["quantity_in_stock"]

    resp = client.post(
        "/api/v1/purchases",
        json={
            "party_id": seeded["supplier_id"],
            "line_items": [
                {"item_code": seeded["item_code"], "qty": 20, "rate": 11000},
                {"item_code": seeded["item_code_2"], "qty": 10, "rate": 4000},
            ],
            "transaction_date": "2026-07-26",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["total_amount"] == 20 * 11000 + 10 * 4000
    assert body["purchase_bill_no"] is not None

    after_a = client.get(f"/api/v1/inventory/{seeded['item_code']}").json()["quantity_in_stock"]
    after_b = client.get(f"/api/v1/inventory/{seeded['item_code_2']}").json()["quantity_in_stock"]
    assert after_a == before_a + 20
    assert after_b == before_b + 10


def test_expense_with_party_real(real_env, seeded):
    client, _ = real_env

    resp = client.post(
        "/api/v1/expenses",
        json={
            "expense_date": "2026-07-27",
            "party_id": seeded["party_id"],
            "description": "ZZTEST fuel receipt",
            "amount": 2500,
            "particular": "Cash",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["amount"] == 2500
    assert body["particular_id"] is not None
    assert body["serial_number"] is not None


def test_unknown_reference_name_rejected_real(real_env, seeded):
    """Section 5.4.F/G: a typo'd master-table name must error, never silently
    create a new row — proves this against real Postgres, not just the fake."""
    client, _ = real_env

    resp = client.post(
        "/api/v1/inventory/create",
        data={
            "item_code": f"{seeded['item_code']}-SHOULD-FAIL",
            "item_name": "Should not be created",
            "unit": "ZZTESTUNIT",
            "rate": "100",
        },
    )
    assert resp.status_code == 400
