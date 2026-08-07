import os

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_user, require_admin
from app.main import app
from app.services import auth_service
from tests.fake_supabase import FakeSupabaseClient

@pytest.fixture(autouse=True)
def _never_hit_real_external_sends(request, monkeypatch):
    """SAFETY NET — applies to every test in this repo automatically, no
    exceptions, EXCEPT the one documented below. A real GMAIL_APP_PASSWORD/
    GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN/OPENAI_API_KEY landing in .env (e.g.
    for a deliberate live smoke test) must NEVER turn a routine `pytest` run
    into real SMTP mail, a real Gmail API call, or a real OpenAI call —
    regardless of whether an individual test file also patches these itself.
    This fixture is intentionally last-resort and redundant with those
    per-test patches; it exists because relying on every test file
    remembering to patch every external call is exactly the gap that let
    real Gmail credentials send real mail during a Phase 3 verification run
    (see progress.md's incident note).

    A test that genuinely needs to exercise the real integration does so in
    tests/integration_real/ under its own explicit ALLOW_LIVE_EXTERNAL_SENDS
    opt-in (see that suite's conftest.py) — this docstring always claimed
    that was already true, but this fixture (being both autouse and
    unconditional, with a name distinct from that suite's own gated fixture)
    silently overrode that opt-in for every external call listed below, so
    it was never actually possible to run a real live-send check through
    pytest — every "verified live" run before 2026-08-06 that used
    email_service.send_email/gmail_client.* through this TestClient had it
    quietly no-op'd, not really sent (found and fixed while building the
    Section 9.2 Send-via-Email live verification, see progress.md). The one
    exception a real live check needs: skip every patch below when the test
    is under tests/integration_real/ AND ALLOW_LIVE_EXTERNAL_SENDS=true —
    matching that suite's own already-gated fixture exactly, and changing
    nothing for tests/unit or tests/integration, which can never satisfy the
    path check and stay exactly as unconditionally protected as before.
    """
    test_path = str(request.node.fspath).replace("\\", "/")
    live_send_intentionally_allowed = (
        "/tests/integration_real/" in test_path
        and os.getenv("ALLOW_LIVE_EXTERNAL_SENDS", "false").lower() == "true"
    )
    if live_send_intentionally_allowed:
        return

    monkeypatch.setattr("app.services.email_service.send_email", lambda *a, **k: None)
    # scheduler.py imports send_email directly (`from ... import send_email`),
    # a separate binding from the one above — both must be patched.
    monkeypatch.setattr("app.services.scheduler.send_email", lambda *a, **k: None)

    monkeypatch.setattr("app.services.gmail_client.list_message_ids", lambda *a, **k: [])

    def _unmocked_gmail_call(*_a, **_k):
        raise AssertionError(
            "A test reached gmail_client without its own explicit mock — this safety net only "
            "no-ops list_message_ids by default. Add a test-specific monkeypatch (see tests/"
            "integration/test_inbox.py for the pattern) rather than relying on real credentials."
        )

    monkeypatch.setattr("app.services.gmail_client.get_message", _unmocked_gmail_call)
    monkeypatch.setattr("app.services.gmail_client.send_message", _unmocked_gmail_call)
    monkeypatch.setattr("app.services.gmail_client.trash_message", lambda *a, **k: None)

    monkeypatch.setattr(
        "app.services.ai_reply_service.generate_reply_draft",
        lambda message, invoice=None: "[test default — no real OpenAI call was made]",
    )

    # Section 5.4.K Scan Slip — same principle, two external calls per scan
    # (Cloudinary upload, OpenAI Vision). Default: no items extracted, so a
    # test that doesn't care about scan-slip specifics gets an empty (not
    # erroring) result; test_scan_slip.py overrides both with per-test data.
    monkeypatch.setattr(
        "app.services.cloudinary_client.upload_scan_slip_image",
        lambda file_bytes: ("https://cdn.example.com/scan-slips/test.jpg", "omega/scan-slips/test"),
    )
    monkeypatch.setattr("app.services.scan_slip_service._extract_line_items", lambda image_url: [])


FAKE_ADMIN_USER = {
    # Must be a syntactically valid UUID, not just any string — the fake client
    # never checks, but real Postgres does the moment a feature persists this id
    # into a UUID column (e.g. app_settings.updated_by), which bit an earlier
    # non-hex id ("...adm1") the first time this ran against real Supabase.
    "id": "99999999-9999-9999-9999-999999999999",
    "full_name": "Test Admin",
    "email": "admin@test.omega",
    "role": "admin",
    "is_active": True,
}


@pytest.fixture
def fake_supabase():
    store = FakeSupabaseClient()
    store.seed("units", "pcs")
    store.seed("units", "box")
    store.seed("categories_1", "Load Cell")
    store.seed("categories_1", "Platform Scales")
    store.seed("categories_2", "Digital")
    store.seed("particulars", "Cash")
    store.seed("particulars", "Cheque")
    store.seed("particulars", "Online")
    store.seed("particulars", "Bank Transfer")
    store.seed("particulars", "Discount")
    store.seed("bank_accounts", "Cash Received", name_field="bank_name", is_active=True)
    store.seed("bank_accounts", "Meezan Bank", name_field="bank_name", is_active=True)
    store.tables["users"].append(dict(FAKE_ADMIN_USER))
    return store


@pytest.fixture
def client(fake_supabase, monkeypatch):
    """The default test client — authenticated as an Admin via a dependency
    override (not a real login), same spirit as the get_supabase override:
    Phase 1/2's existing tests exercise business logic, not auth itself, so
    they keep running unauthenticated-as-far-as-they-know. Dedicated auth/RBAC
    behavior (401s, 403s, real login/cookie flow) is tested separately via the
    `raw_client` fixture below, which does NOT override these two."""
    monkeypatch.setattr(
        "app.services.cloudinary_client.upload_item_image",
        lambda file_bytes, item_code: (f"https://cdn.example.com/{item_code}.jpg", f"omega/{item_code}"),
    )
    monkeypatch.setattr("app.services.cloudinary_client.delete_item_image", lambda public_id: None)
    # the router imports these names directly, so patch them there too
    monkeypatch.setattr(
        "app.routers.inventory.upload_item_image",
        lambda file_bytes, item_code: (f"https://cdn.example.com/{item_code}.jpg", f"omega/{item_code}"),
    )
    monkeypatch.setattr("app.routers.inventory.delete_item_image", lambda public_id: None)
    # Section 10.2b's bulk-upload image matching imports this name directly too —
    # a third binding, same reasoning as the router patch above.
    monkeypatch.setattr(
        "app.services.bulk_upload.upload_item_image",
        lambda file_bytes, item_code: (f"https://cdn.example.com/{item_code}.jpg", f"omega/{item_code}"),
    )

    app.dependency_overrides[get_supabase] = lambda: fake_supabase
    app.dependency_overrides[get_current_user] = lambda: FAKE_ADMIN_USER
    app.dependency_overrides[require_admin] = lambda: FAKE_ADMIN_USER
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def raw_client(fake_supabase, monkeypatch):
    """A client with NO auth override — real login/cookie/RBAC behavior, for
    tests/integration/test_auth.py and test_login_approval_gate.py."""
    monkeypatch.setattr(
        "app.services.cloudinary_client.upload_item_image",
        lambda file_bytes, item_code: (f"https://cdn.example.com/{item_code}.jpg", f"omega/{item_code}"),
    )
    monkeypatch.setattr("app.services.cloudinary_client.delete_item_image", lambda public_id: None)

    app.dependency_overrides[get_supabase] = lambda: fake_supabase
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def admin_password():
    return "AdminPass123!"


@pytest.fixture
def staff_password():
    return "StaffPass123!"


@pytest.fixture
def seeded_admin(fake_supabase, admin_password):
    """A second, real (non-override) admin — distinct from FAKE_ADMIN_USER
    above, which only exists for the dependency-override `client` fixture."""
    row = {
        "id": "10000000-0000-0000-0000-000000000001",
        "full_name": "Real Admin",
        "email": "real.admin@test.omega",
        "role": "admin",
        "is_active": True,
        "password_hash": auth_service.hash_password(admin_password),
        "failed_login_attempts": 0,
    }
    fake_supabase.tables["users"].append(row)
    return row


@pytest.fixture
def seeded_second_admin(fake_supabase, admin_password):
    row = {
        "id": "10000000-0000-0000-0000-000000000002",
        "full_name": "Second Admin",
        "email": "second.admin@test.omega",
        "role": "admin",
        "is_active": True,
        "password_hash": auth_service.hash_password(admin_password),
        "failed_login_attempts": 0,
    }
    fake_supabase.tables["users"].append(row)
    return row


@pytest.fixture
def seeded_staff(fake_supabase, staff_password):
    row = {
        "id": "20000000-0000-0000-0000-000000000001",
        "full_name": "Real Staff",
        "email": "real.staff@test.omega",
        "role": "staff",
        "is_active": True,
        "password_hash": auth_service.hash_password(staff_password),
        "failed_login_attempts": 0,
    }
    fake_supabase.tables["users"].append(row)
    return row


@pytest.fixture
def party_id(client):
    resp = client.post("/api/v1/parties", json={"party_name": "United Scale Ijtibah", "party_type": "customer"})
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest.fixture
def supplier_id(client):
    resp = client.post("/api/v1/parties", json={"party_name": "Acme Supplier Co", "party_type": "supplier"})
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest.fixture
def item_code(client):
    resp = client.post(
        "/api/v1/inventory/create",
        data={
            "item_code": "P-16-S-A-MK",
            "item_name": "Platform 400x400 SS Top Cap.150Kg 10g (MK-03)",
            "unit": "pcs",
            "rate": "12300",
            "quantity_in_stock": "100",
        },
    )
    assert resp.status_code == 201
    return resp.json()["item_code"]
