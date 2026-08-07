"""Section 16.6 — Payment Correction ('Fix This Payment'), Admin-only, mirroring
Section 5.1's Correction Entry pattern but for a recorded payment instead of a sale."""


def _record_payment(client, party_id, amount):
    return client.post(
        "/api/v1/invoices/payments",
        json={"party_id": party_id, "amount": amount, "method": "Cash", "transaction_date": "2026-07-30"},
    ).json()


def test_correct_payment_amount_lower_increases_balance_back(client, party_id):
    payment = _record_payment(client, party_id, 5000)
    before_balance = payment["current_balance"]

    resp = client.post(
        f"/api/v1/invoices/payments/{payment['id']}/correct",
        json={"reason": "Party actually only paid Rs. 3000", "corrected_amount": 3000},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["payment_correction_of"] == payment["id"]
    assert body["payment_correction_reason"] == "Party actually only paid Rs. 3000"
    # delta = 5000 - 3000 = 2000, balance goes back UP by 2000
    assert body["current_balance"] == before_balance + 2000
    assert body["total_amount"] == 2000
    assert body["txn_type"] == "sale"


def test_correct_payment_amount_higher_decreases_balance_further(client, party_id):
    payment = _record_payment(client, party_id, 5000)
    before_balance = payment["current_balance"]

    resp = client.post(
        f"/api/v1/invoices/payments/{payment['id']}/correct",
        json={"reason": "Party actually paid Rs. 7000", "corrected_amount": 7000},
    )
    assert resp.status_code == 201
    body = resp.json()
    # delta = 5000 - 7000 = -2000, balance goes DOWN by 2000 further
    assert body["current_balance"] == before_balance - 2000
    assert body["total_amount"] == 2000
    assert body["txn_type"] == "receiving"


def test_correct_payment_metadata_only_no_balance_change(client, party_id):
    payment = _record_payment(client, party_id, 5000)
    before_balance = payment["current_balance"]

    resp = client.post(
        f"/api/v1/invoices/payments/{payment['id']}/correct",
        json={"reason": "Wrong method recorded", "corrected_method": "Cheque"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["current_balance"] == before_balance
    assert body["total_amount"] == 0
    assert "Method corrected to Cheque" in body["payment_note"]

    # original payment itself is never mutated
    original = client.get(f"/api/v1/invoices/{payment['id']}").json()
    assert original["current_balance"] == before_balance


def test_correct_payment_never_mutates_original_row(client, party_id):
    payment = _record_payment(client, party_id, 5000)
    client.post(
        f"/api/v1/invoices/payments/{payment['id']}/correct",
        json={"reason": "Test", "corrected_amount": 4000},
    )
    original = client.get(f"/api/v1/invoices/{payment['id']}").json()
    assert original["total_amount"] == 5000
    assert original["payment_correction_of"] is None


def test_correct_payment_rejects_a_sale_invoice_id(client, party_id, item_code):
    draft = client.post(
        "/api/v1/invoices/draft",
        json={"party_id": party_id, "line_items": [{"item_code": item_code, "qty": 1, "rate": 1000}], "transaction_date": "2026-07-30"},
    ).json()
    finalized = client.post(f"/api/v1/invoices/{draft['id']}/finalize").json()

    resp = client.post(
        f"/api/v1/invoices/payments/{finalized['id']}/correct",
        json={"reason": "Not a payment"},
    )
    assert resp.status_code == 404


def test_correct_payment_unknown_id_404s(client):
    resp = client.post(
        "/api/v1/invoices/payments/00000000-0000-0000-0000-000000000000/correct",
        json={"reason": "Doesn't exist"},
    )
    assert resp.status_code == 404


def test_staff_cannot_correct_a_payment(raw_client, fake_supabase, seeded_staff, staff_password):
    from app.services import auth_service

    fake_supabase.tables["customer_ledgers"].append(
        {
            "id": "cccccccc-0000-0000-0000-000000000001",
            "party_id": "aaaaaaaa-0000-0000-0000-000000000099",
            "invoice_state": "finalized",
            "invoice_status": "paid",
            "txn_type": "receiving",
            "transaction_date": "2026-07-30",
            "discount_amount": "0",
            "total_amount": "5000",
            "previous_balance": "0",
            "current_balance": "-5000",
            "approval_status": "approved",
            "deleted_at": None,
        }
    )

    token = auth_service.create_access_token(seeded_staff["id"], seeded_staff["role"])
    raw_client.cookies.set("omega_session", token)

    resp = raw_client.post(
        "/api/v1/invoices/payments/cccccccc-0000-0000-0000-000000000001/correct",
        json={"reason": "Staff attempt"},
    )
    assert resp.status_code == 403
