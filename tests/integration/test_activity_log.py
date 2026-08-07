"""Section 16.4 — Activity Log. Read-only, Admin-only; entries are written by
the sensitive actions themselves via activity_log_service.log_activity."""

from app.services.activity_log_service import log_activity


def test_list_activity_log_returns_entries_newest_first(client, fake_supabase):
    from tests.conftest import FAKE_ADMIN_USER

    log_activity(fake_supabase, FAKE_ADMIN_USER["id"], "rate_change", "Changed rate on P-1 from Rs. 100 to Rs. 120")
    log_activity(fake_supabase, FAKE_ADMIN_USER["id"], "user_deactivated", "Deactivated Jane Doe")

    resp = client.get("/api/v1/activity-log")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["action"] == "user_deactivated"  # newest first
    assert body[0]["user_name"] == FAKE_ADMIN_USER["full_name"]


def test_filter_by_action(client, fake_supabase):
    from tests.conftest import FAKE_ADMIN_USER

    log_activity(fake_supabase, FAKE_ADMIN_USER["id"], "rate_change", "Changed rate on P-1")
    log_activity(fake_supabase, FAKE_ADMIN_USER["id"], "credit_override", "Overrode credit limit for United Scale")

    resp = client.get("/api/v1/activity-log", params={"action": "credit_override"})
    body = resp.json()
    assert len(body) == 1
    assert body[0]["action"] == "credit_override"


def test_search_matches_target_description_substring(client, fake_supabase):
    from tests.conftest import FAKE_ADMIN_USER

    log_activity(fake_supabase, FAKE_ADMIN_USER["id"], "rate_change", "Changed rate on P-16-S-A-MK from Rs. 12,000 to Rs. 12,300")
    log_activity(fake_supabase, FAKE_ADMIN_USER["id"], "user_deactivated", "Deactivated Jane Doe")

    resp = client.get("/api/v1/activity-log", params={"search": "P-16-S-A-MK"})
    body = resp.json()
    assert len(body) == 1
    assert "P-16-S-A-MK" in body[0]["target_description"]


def test_activity_log_is_admin_only(raw_client, seeded_staff, staff_password):
    from app.services import auth_service

    token = auth_service.create_access_token(seeded_staff["id"], seeded_staff["role"])
    raw_client.cookies.set("omega_session", token)
    resp = raw_client.get("/api/v1/activity-log")
    assert resp.status_code == 403


def test_activity_log_has_no_delete_or_update_route(client):
    """Section 16.4: 'even Admin cannot soft-delete rows.' Confirmed by the
    absence of the route itself, not just an RBAC check — no route was ever
    registered that takes an id, so this 404s rather than 403/405."""
    resp = client.delete("/api/v1/activity-log/some-id")
    assert resp.status_code == 404


def test_creating_a_user_is_logged(client):
    """Section 16.4: 'wired into every sensitive write already happening' —
    account creation is one of the pre-existing Admin-only writes retrofitted."""
    resp = client.post("/api/v1/users", json={"full_name": "Zeeshan Khan", "email": "zeeshan@example.com", "role": "staff"})
    assert resp.status_code == 201

    log = client.get("/api/v1/activity-log").json()
    assert any(entry["action"] == "user_created" and "Zeeshan Khan" in entry["target_description"] for entry in log)


def test_deactivating_a_user_is_logged(client):
    created = client.post("/api/v1/users", json={"full_name": "Ali Raza", "email": "ali@example.com", "role": "staff"}).json()

    resp = client.patch(f"/api/v1/users/{created['id']}/deactivate")
    assert resp.status_code == 200

    log = client.get("/api/v1/activity-log").json()
    assert any(entry["action"] == "user_deactivated" and "Ali Raza" in entry["target_description"] for entry in log)


def test_deleting_an_inventory_item_is_logged(client, item_code):
    resp = client.delete(f"/api/v1/inventory/{item_code}")
    assert resp.status_code == 204

    log = client.get("/api/v1/activity-log").json()
    assert any(entry["action"] == "item_deleted" and item_code in entry["target_description"] for entry in log)
