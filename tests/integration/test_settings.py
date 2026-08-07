"""Section 12.1 — Human Gate threshold must be Admin-editable and actually
change gate behavior when saved, not just a display value."""

from app.services import auth_service


def test_admin_sees_and_can_update_the_threshold(client):
    get_resp = client.get("/api/v1/settings")
    assert get_resp.status_code == 200
    assert get_resp.json()["human_gate_threshold"] == 100000.00

    patch_resp = client.patch("/api/v1/settings", json={"human_gate_threshold": 50000})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["human_gate_threshold"] == 50000.0

    confirm = client.get("/api/v1/settings")
    assert confirm.json()["human_gate_threshold"] == 50000.0


def test_lowering_the_threshold_actually_changes_gate_behavior(client, party_id, item_code):
    """qty=5 x rate=12300 = 61,500 — under the default 100,000 threshold, but
    above a lowered 50,000 one."""
    client.patch("/api/v1/settings", json={"human_gate_threshold": 50000})

    draft = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": 5}],
            "transaction_date": "2026-07-23",
        },
    )
    invoice_id = draft.json()["id"]
    finalized = client.post(f"/api/v1/invoices/{invoice_id}/finalize")
    assert finalized.json()["approval_status"] == "pending"


def test_staff_gets_a_reduced_view_without_the_threshold_field(raw_client, seeded_staff):
    token = auth_service.create_access_token(seeded_staff["id"], seeded_staff["role"])
    raw_client.cookies.set("omega_session", token)

    resp = raw_client.get("/api/v1/settings")
    assert resp.status_code == 200
    assert resp.json()["human_gate_threshold"] is None


def test_staff_cannot_update_the_threshold(raw_client, seeded_staff):
    token = auth_service.create_access_token(seeded_staff["id"], seeded_staff["role"])
    raw_client.cookies.set("omega_session", token)

    resp = raw_client.patch("/api/v1/settings", json={"human_gate_threshold": 1})
    assert resp.status_code == 403
