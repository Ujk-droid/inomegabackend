"""Section 3 — auth foundation + RBAC retrofit. Uses `raw_client` (no auth
dependency override) since these tests are exactly about the auth behavior
the `client` fixture bypasses for everyone else's tests."""


def test_admin_logs_in_directly_and_gets_a_session(raw_client, seeded_admin, admin_password):
    """Section 3: 'Admin accounts log in directly — no approval needed.'"""
    resp = raw_client.post(
        "/api/v1/auth/login", json={"email": seeded_admin["email"], "password": admin_password}
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "authenticated", "role": "admin", "request_id": None}
    assert "omega_session" in resp.cookies

    me = raw_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == seeded_admin["email"]


def test_staff_login_creates_a_pending_request_and_no_cookie(raw_client, seeded_staff, staff_password):
    """Section 3.1: a Staff login never lands directly in the app."""
    resp = raw_client.post(
        "/api/v1/auth/login", json={"email": seeded_staff["email"], "password": staff_password}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["request_id"]
    assert "omega_session" not in resp.cookies

    poll = raw_client.get(f"/api/v1/auth/login-requests/{body['request_id']}/status")
    assert poll.status_code == 200
    assert poll.json()["status"] == "pending"


def test_wrong_password_returns_generic_incorrect_message(raw_client, seeded_admin):
    resp = raw_client.post(
        "/api/v1/auth/login", json={"email": seeded_admin["email"], "password": "not-the-password"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Incorrect email or password"


def test_unknown_email_returns_the_same_generic_message(raw_client, fake_supabase):
    resp = raw_client.post(
        "/api/v1/auth/login", json={"email": "nobody@nowhere.omega", "password": "whatever"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Incorrect email or password"


def test_five_failed_attempts_locks_the_account(raw_client, seeded_admin):
    """Section 3: '5 failed attempts locks the account for 15 minutes.'"""
    for _ in range(5):
        resp = raw_client.post(
            "/api/v1/auth/login", json={"email": seeded_admin["email"], "password": "wrong"}
        )
        assert resp.status_code == 401

    # even the CORRECT password is now rejected — the account is locked, not the credential
    locked_resp = raw_client.post(
        "/api/v1/auth/login", json={"email": seeded_admin["email"], "password": "AdminPass123!"}
    )
    assert locked_resp.status_code == 423


def test_deactivated_user_cannot_log_in(raw_client, seeded_admin, admin_password, fake_supabase):
    for row in fake_supabase.tables["users"]:
        if row["id"] == seeded_admin["id"]:
            row["is_active"] = False

    resp = raw_client.post(
        "/api/v1/auth/login", json={"email": seeded_admin["email"], "password": admin_password}
    )
    assert resp.status_code == 403


def test_protected_endpoint_rejects_unauthenticated_request(raw_client):
    resp = raw_client.get("/api/v1/inventory")
    assert resp.status_code == 401


def test_staff_never_receives_a_cookie_while_pending(raw_client, seeded_staff, staff_password):
    login = raw_client.post(
        "/api/v1/auth/login", json={"email": seeded_staff["email"], "password": staff_password}
    )
    request_id = login.json()["request_id"]

    resp = raw_client.get("/api/v1/users")
    assert resp.status_code == 401  # never got a cookie — the request is still pending

    poll = raw_client.get(f"/api/v1/auth/login-requests/{request_id}/status")
    assert poll.json()["status"] == "pending"
    assert "omega_session" not in poll.cookies


def test_admin_only_endpoint_rejects_a_logged_in_staff_member(raw_client, seeded_staff):
    """Section 3 RBAC: Staff 'Cannot ... invite/deactivate other users, or
    access User Management.' A Staff session (post-approval) must still be
    blocked from Admin-only routes — this issues the same JWT the app would
    issue after an Admin approves, so RBAC is tested independently of the
    Login Approval Gate flow itself (covered in test_login_approval_gate.py)."""
    from app.services import auth_service

    token = auth_service.create_access_token(seeded_staff["id"], seeded_staff["role"])
    raw_client.cookies.set("omega_session", token)

    resp = raw_client.get("/api/v1/users")
    assert resp.status_code == 403

    ok = raw_client.get("/api/v1/inventory")
    assert ok.status_code == 200
