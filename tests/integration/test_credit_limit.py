"""Section 16.1 — Credit Limit Enforcement."""


def _party_with_limit(client, limit):
    return client.post(
        "/api/v1/parties", json={"party_name": "Limited Party", "party_type": "customer", "credit_limit": limit}
    ).json()["id"]


def test_finalize_blocked_when_it_would_exceed_credit_limit(client, item_code):
    party_id = _party_with_limit(client, 10000)
    draft = client.post(
        "/api/v1/invoices/draft",
        json={"party_id": party_id, "line_items": [{"item_code": item_code, "qty": 1, "rate": 15000}], "transaction_date": "2026-07-30"},
    ).json()

    resp = client.post(f"/api/v1/invoices/{draft['id']}/finalize")
    assert resp.status_code == 409
    assert "credit limit of Rs. 10,000.00" in resp.json()["detail"]
    assert "by Rs. 5,000.00" in resp.json()["detail"]

    # blocked finalize is a true no-op — still draft, stock untouched
    unchanged = client.get(f"/api/v1/invoices/{draft['id']}").json()
    assert unchanged["invoice_state"] == "draft"


def test_finalize_within_credit_limit_succeeds(client, item_code):
    party_id = _party_with_limit(client, 10000)
    draft = client.post(
        "/api/v1/invoices/draft",
        json={"party_id": party_id, "line_items": [{"item_code": item_code, "qty": 1, "rate": 8000}], "transaction_date": "2026-07-30"},
    ).json()

    resp = client.post(f"/api/v1/invoices/{draft['id']}/finalize")
    assert resp.status_code == 200
    assert resp.json()["invoice_state"] == "finalized"


def test_no_credit_limit_never_blocks(client, party_id, item_code):
    """party_id fixture has no credit_limit set — null means no limit enforced (Section 5)."""
    draft = client.post(
        "/api/v1/invoices/draft",
        json={"party_id": party_id, "line_items": [{"item_code": item_code, "qty": 1, "rate": 999999}], "transaction_date": "2026-07-30"},
    ).json()
    resp = client.post(f"/api/v1/invoices/{draft['id']}/finalize")
    assert resp.status_code == 200


def test_admin_override_succeeds_and_is_logged(client, item_code):
    party_id = _party_with_limit(client, 10000)
    draft = client.post(
        "/api/v1/invoices/draft",
        json={"party_id": party_id, "line_items": [{"item_code": item_code, "qty": 1, "rate": 15000}], "transaction_date": "2026-07-30"},
    ).json()

    resp = client.post(f"/api/v1/invoices/{draft['id']}/finalize", params={"override_credit_limit": "true"})
    assert resp.status_code == 200
    assert resp.json()["invoice_state"] == "finalized"

    log = client.get("/api/v1/activity-log").json()
    assert len(log) == 1
    assert log[0]["action"] == "credit_override"
    assert "Limited Party" in log[0]["target_description"]


def test_staff_cannot_override_credit_limit(raw_client, fake_supabase, seeded_staff, staff_password):
    """Section 16.1: 'Staff cannot override, only Admin.' raw_client has no
    auth-dependency override (unlike `client`), so data is seeded directly
    and a real Staff session cookie is used to hit the endpoint."""
    from app.services import auth_service

    fake_supabase.tables["parties"].append(
        {"id": "aaaaaaaa-0000-0000-0000-000000000001", "party_name": "Staff Blocked Party", "party_type": "customer", "credit_limit": "5000"}
    )
    fake_supabase.tables["inventory_items"].append(
        {"id": "bbbbbbbb-0000-0000-0000-000000000001", "item_code": "STAFF-ITEM", "item_name": "Staff Item", "unit": "pcs", "rate": "10000", "quantity_in_stock": 10, "min_threshold": 2}
    )

    token = auth_service.create_access_token(seeded_staff["id"], seeded_staff["role"])
    raw_client.cookies.set("omega_session", token)

    draft = raw_client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": "aaaaaaaa-0000-0000-0000-000000000001",
            "line_items": [{"item_code": "STAFF-ITEM", "qty": 1, "rate": 10000}],
            "transaction_date": "2026-07-30",
        },
    ).json()

    resp = raw_client.post(f"/api/v1/invoices/{draft['id']}/finalize", params={"override_credit_limit": "true"})
    assert resp.status_code == 403
