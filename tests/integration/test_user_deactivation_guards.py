"""Real gap found during the pre-deployment audit (2026-08-04): there was no
reactivate endpoint anywhere and no server-side guard against an Admin
deactivating their own account or the system's last active Admin — either one
permanently locks the app out of every Admin-gated feature, including User
Management itself, with no recovery path short of manual DB access."""

from tests.conftest import FAKE_ADMIN_USER


def test_admin_cannot_deactivate_their_own_account(client):
    resp = client.patch(f"/api/v1/users/{FAKE_ADMIN_USER['id']}/deactivate")
    assert resp.status_code == 409
    assert "own account" in resp.json()["detail"].lower()


def test_cannot_deactivate_the_last_active_admin(client, fake_supabase):
    second_admin = client.post(
        "/api/v1/users", json={"full_name": "Second Admin", "email": "second-admin@example.com", "role": "admin"}
    ).json()

    # FAKE_ADMIN_USER (the acting admin, via the test client's dependency
    # override) is deactivated directly in the store here, bypassing the API,
    # purely to simulate "no other active admin remains" — the self-deactivate
    # guard above already covers the API path for FAKE_ADMIN_USER itself.
    for row in fake_supabase.tables["users"]:
        if row["id"] == FAKE_ADMIN_USER["id"]:
            row["is_active"] = False

    resp = client.patch(f"/api/v1/users/{second_admin['id']}/deactivate")
    assert resp.status_code == 409
    assert "last active admin" in resp.json()["detail"].lower()


def test_can_deactivate_an_admin_when_another_active_admin_remains(client):
    second_admin = client.post(
        "/api/v1/users", json={"full_name": "Second Admin", "email": "second-admin-2@example.com", "role": "admin"}
    ).json()

    # FAKE_ADMIN_USER is still active, so deactivating this one is fine.
    resp = client.patch(f"/api/v1/users/{second_admin['id']}/deactivate")
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False
