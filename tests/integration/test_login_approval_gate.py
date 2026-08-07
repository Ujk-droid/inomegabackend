"""Section 3.1 — Login Approval Gate: approve/reject, the race between two
Admins, and the 10-minute auto-expiry. Mirrors test_human_gate.py's structure
(full black-box HTTP round trips against the fake Supabase client)."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.services import login_gate_service


def _login_staff(client, seeded_staff, staff_password) -> str:
    resp = client.post(
        "/api/v1/auth/login", json={"email": seeded_staff["email"], "password": staff_password}
    )
    assert resp.status_code == 200
    return resp.json()["request_id"]


def _login_admin(client, admin_row, admin_password) -> None:
    resp = client.post(
        "/api/v1/auth/login", json={"email": admin_row["email"], "password": admin_password}
    )
    assert resp.status_code == 200


def test_admin_can_approve_a_pending_staff_login(raw_client, seeded_admin, seeded_staff, admin_password, staff_password):
    admin_client = TestClient(app)
    staff_client = TestClient(app)

    request_id = _login_staff(staff_client, seeded_staff, staff_password)
    _login_admin(admin_client, seeded_admin, admin_password)

    approve = admin_client.post(f"/api/v1/login-requests/{request_id}/approve")
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"

    # Section 3.1: "the waiting Staff session activates immediately... no need
    # for them to log in again" — the SAME poll call sets their session cookie.
    poll = staff_client.get(f"/api/v1/auth/login-requests/{request_id}/status")
    assert poll.json()["status"] == "approved"
    assert "omega_session" in poll.cookies

    now_in_app = staff_client.get("/api/v1/inventory")
    assert now_in_app.status_code == 200


def test_admin_can_reject_a_pending_staff_login(raw_client, seeded_admin, seeded_staff, admin_password, staff_password):
    admin_client = TestClient(app)
    staff_client = TestClient(app)

    request_id = _login_staff(staff_client, seeded_staff, staff_password)
    _login_admin(admin_client, seeded_admin, admin_password)

    reject = admin_client.post(f"/api/v1/login-requests/{request_id}/reject")
    assert reject.status_code == 200
    assert reject.json()["status"] == "rejected"

    poll = staff_client.get(f"/api/v1/auth/login-requests/{request_id}/status")
    assert poll.json()["status"] == "rejected"
    assert "omega_session" not in poll.cookies


def test_second_admin_gets_409_once_the_first_admin_already_acted(
    raw_client, seeded_admin, seeded_second_admin, seeded_staff, admin_password, staff_password
):
    """Section 3.1: 'whichever Admin acts first resolves it; the other sees it
    move out of their pending queue too, so two Admins never approve/reject
    the same request twice.'"""
    admin_one = TestClient(app)
    admin_two = TestClient(app)
    staff_client = TestClient(app)

    request_id = _login_staff(staff_client, seeded_staff, staff_password)
    _login_admin(admin_one, seeded_admin, admin_password)
    _login_admin(admin_two, seeded_second_admin, admin_password)

    first = admin_one.post(f"/api/v1/login-requests/{request_id}/approve")
    assert first.status_code == 200

    second = admin_two.post(f"/api/v1/login-requests/{request_id}/reject")
    assert second.status_code == 409


def test_pending_request_older_than_ten_minutes_expires(raw_client, fake_supabase, seeded_staff, staff_password):
    staff_client = TestClient(app)
    request_id = _login_staff(staff_client, seeded_staff, staff_password)

    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    for row in fake_supabase.tables["login_requests"]:
        if row["id"] == request_id:
            row["requested_at"] = stale_time

    expired = login_gate_service.expire_stale_requests(fake_supabase)
    assert len(expired) == 1
    assert expired[0]["status"] == "expired"

    poll = staff_client.get(f"/api/v1/auth/login-requests/{request_id}/status")
    assert poll.json()["status"] == "expired"


def test_login_approvals_list_search_and_soft_delete(raw_client, seeded_admin, seeded_staff, admin_password, staff_password):
    admin_client = TestClient(app)
    staff_client = TestClient(app)

    request_id = _login_staff(staff_client, seeded_staff, staff_password)
    _login_admin(admin_client, seeded_admin, admin_password)

    listed = admin_client.get("/api/v1/login-requests", params={"status": "pending"})
    assert listed.status_code == 200
    assert any(r["id"] == request_id for r in listed.json())

    note = admin_client.patch(f"/api/v1/login-requests/{request_id}/note", json={"note": "known device"})
    assert note.status_code == 200
    assert note.json()["note"] == "known device"

    deleted = admin_client.delete(f"/api/v1/login-requests/{request_id}")
    assert deleted.status_code == 204

    after_delete = admin_client.get("/api/v1/login-requests")
    assert all(r["id"] != request_id for r in after_delete.json())


def test_login_approvals_are_admin_only(raw_client, seeded_staff):
    from app.services import auth_service

    staff_client = TestClient(app)
    token = auth_service.create_access_token(seeded_staff["id"], seeded_staff["role"])
    staff_client.cookies.set("omega_session", token)

    resp = staff_client.get("/api/v1/login-requests")
    assert resp.status_code == 403
