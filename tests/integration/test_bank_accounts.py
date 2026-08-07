"""Screen 18 — Bank Accounts, Admin-only full CRUD (Section 5.4.E)."""


def test_list_bank_accounts_returns_seeded_rows(client):
    resp = client.get("/api/v1/bank-accounts")
    assert resp.status_code == 200
    names = {row["bank_name"] for row in resp.json()}
    assert names == {"Cash Received", "Meezan Bank"}


def test_create_bank_account(client):
    resp = client.post("/api/v1/bank-accounts", json={"bank_name": "HBL", "account_note": "Main account"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["bank_name"] == "HBL"
    assert body["account_note"] == "Main account"
    assert body["is_active"] is True


def test_deactivate_bank_account(client):
    created = client.post("/api/v1/bank-accounts", json={"bank_name": "UBL"}).json()
    resp = client.patch(f"/api/v1/bank-accounts/{created['id']}", json={"is_active": False})
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    # Section 5.0's Record Payment picker only ever shows active banks —
    # deactivating one here must remove it from that list immediately.
    active_names = client.get("/api/v1/master-data/bank-accounts").json()["bank_accounts"]
    assert "UBL" not in active_names


def test_deactivated_bank_account_cannot_be_used_to_record_a_payment(client, party_id):
    """The Record Payment picker hides a deactivated bank client-side, but
    that's cosmetic only — a stale client or a direct API call must still be
    rejected server-side, not silently record against a bank an Admin already
    turned off."""
    created = client.post("/api/v1/bank-accounts", json={"bank_name": "Deactivated Bank"}).json()
    client.patch(f"/api/v1/bank-accounts/{created['id']}", json={"is_active": False})

    resp = client.post(
        "/api/v1/invoices/payments",
        json={
            "party_id": party_id,
            "amount": 5000,
            "method": "Bank Transfer",
            "bank_name": "Deactivated Bank",
            "transaction_date": "2026-07-30",
        },
    )
    assert resp.status_code == 400


def test_update_unknown_bank_account_404s(client):
    resp = client.patch("/api/v1/bank-accounts/00000000-0000-0000-0000-000000000000", json={"is_active": False})
    assert resp.status_code == 404


def test_bank_accounts_are_admin_only(raw_client, seeded_staff, staff_password):
    from app.services import auth_service

    token = auth_service.create_access_token(seeded_staff["id"], seeded_staff["role"])
    raw_client.cookies.set("omega_session", token)
    resp = raw_client.get("/api/v1/bank-accounts")
    assert resp.status_code == 403
