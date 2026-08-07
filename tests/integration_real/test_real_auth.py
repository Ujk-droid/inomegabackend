"""Phase 3 auth foundation + Login Approval Gate, replayed against the REAL
Supabase project — a real login round trip (JWT cookie), not the
`get_current_user`/`require_admin` dependency override that `real_env`
(test_real_supabase.py's fixture) uses. Deliberately does NOT request that
fixture or touch its overrides; every user row here is its own fixture,
function-scoped so login_requests state never bleeds between tests, and is
deleted in teardown (FK-safe: login_requests before users) whether or not the
test passes."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.main import app
from app.services import auth_service

ADMIN_PASSWORD = "ZZTestAdminPass123!"
STAFF_PASSWORD = "ZZTestStaffPass123!"


@pytest.fixture
def real_users():
    supabase = get_supabase()
    run_id = uuid.uuid4().hex[:8]
    created_ids = []

    def _make(role, label):
        payload = {
            "full_name": f"ZZTEST {label} {run_id}",
            "email": f"zztest.{label}.{run_id}@example.com",
            "role": role,
            "password_hash": auth_service.hash_password(ADMIN_PASSWORD if role == "admin" else STAFF_PASSWORD),
            "is_active": True,
        }
        resp = supabase.table("users").insert(payload).execute()
        row = resp.data[0]
        created_ids.append(row["id"])
        return row

    admin1 = _make("admin", "AdminOne")
    admin2 = _make("admin", "AdminTwo")
    staff = _make("staff", "StaffOne")

    try:
        yield {"admin1": admin1, "admin2": admin2, "staff": staff}
    finally:
        supabase.table("login_requests").delete().eq("user_id", staff["id"]).execute()
        for uid in created_ids:
            supabase.table("users").delete().eq("id", uid).execute()


def _login(client, email, password):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_admin_logs_in_directly_real(real_users):
    client = TestClient(app)
    resp = _login(client, real_users["admin1"]["email"], ADMIN_PASSWORD)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "authenticated"
    assert "omega_session" in resp.cookies

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == real_users["admin1"]["email"]


def test_staff_login_pending_then_admin_approves_and_staff_gets_cookie_real(real_users):
    staff_client = TestClient(app)
    admin_client = TestClient(app)

    staff_resp = _login(staff_client, real_users["staff"]["email"], STAFF_PASSWORD)
    assert staff_resp.status_code == 200, staff_resp.text
    body = staff_resp.json()
    assert body["status"] == "pending"
    assert "omega_session" not in staff_resp.cookies
    request_id = body["request_id"]

    _login(admin_client, real_users["admin1"]["email"], ADMIN_PASSWORD)
    approve = admin_client.post(f"/api/v1/login-requests/{request_id}/approve")
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == "approved"

    poll = staff_client.get(f"/api/v1/auth/login-requests/{request_id}/status")
    assert poll.json()["status"] == "approved"
    assert "omega_session" in poll.cookies

    now_in = staff_client.get("/api/v1/inventory")
    assert now_in.status_code == 200


def test_second_admin_cannot_double_resolve_real(real_users):
    staff_client = TestClient(app)
    admin1_client = TestClient(app)
    admin2_client = TestClient(app)

    staff_resp = _login(staff_client, real_users["staff"]["email"], STAFF_PASSWORD)
    request_id = staff_resp.json()["request_id"]

    _login(admin1_client, real_users["admin1"]["email"], ADMIN_PASSWORD)
    _login(admin2_client, real_users["admin2"]["email"], ADMIN_PASSWORD)

    first = admin1_client.post(f"/api/v1/login-requests/{request_id}/approve")
    assert first.status_code == 200

    second = admin2_client.post(f"/api/v1/login-requests/{request_id}/reject")
    assert second.status_code == 409


def test_rbac_blocks_a_real_staff_session_from_admin_only_route_real(real_users):
    staff_client = TestClient(app)
    admin_client = TestClient(app)

    staff_resp = _login(staff_client, real_users["staff"]["email"], STAFF_PASSWORD)
    request_id = staff_resp.json()["request_id"]

    _login(admin_client, real_users["admin1"]["email"], ADMIN_PASSWORD)
    admin_client.post(f"/api/v1/login-requests/{request_id}/approve")
    staff_client.get(f"/api/v1/auth/login-requests/{request_id}/status")  # picks up the session cookie

    blocked = staff_client.get("/api/v1/users")
    assert blocked.status_code == 403

    unrelated_admin_can = admin_client.get("/api/v1/users")
    assert unrelated_admin_can.status_code == 200
