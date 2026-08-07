"""Fixture plumbing for the real-Supabase integration suite (tests/integration_real).

Unlike tests/conftest.py's `client` fixture, nothing here overrides
`app.database.get_supabase` — these tests exercise the actual live Supabase
project configured in .env. Every row created is prefixed with a run-unique
ZZTEST_ marker and is deleted by `real_env`'s teardown in FK-safe order,
whether or not the tests pass.
"""

import os
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_user, require_admin
from app.main import app
from app.services import auth_service

RUN_ID = uuid.uuid4().hex[:8]

# INCIDENT (see progress.md): a real GMAIL_APP_PASSWORD/GMAIL_CLIENT_ID/SECRET/
# REFRESH_TOKEN landing in .env caused this suite to send real mail to real
# Admin accounts on every routine run — test_real_auth.py's staff-login tests
# each trigger a real admin-notification email to EVERY active admin in the
# real `users` table (not just the two ZZTEST ones the test created), and
# test_real_dispatch_settings_analytics.py has its own real send/digest/sync
# tests. Default to mocked; a deliberate one-time live smoke test opts in
# explicitly with ALLOW_LIVE_EXTERNAL_SENDS=true — never implicitly.
ALLOW_LIVE_EXTERNAL_SENDS = os.getenv("ALLOW_LIVE_EXTERNAL_SENDS", "false").lower() == "true"


@pytest.fixture(autouse=True)
def _never_hit_real_external_sends_unless_explicitly_allowed(monkeypatch):
    if ALLOW_LIVE_EXTERNAL_SENDS:
        return  # deliberate, explicit opt-in for a one-time live smoke test — see module docstring above

    monkeypatch.setattr("app.services.email_service.send_email", lambda *a, **k: None)
    monkeypatch.setattr("app.services.scheduler.send_email", lambda *a, **k: None)
    monkeypatch.setattr("app.services.gmail_client.list_message_ids", lambda *a, **k: [])

    def _unmocked_gmail_call(*_a, **_k):
        raise AssertionError("A real-DB test reached gmail_client without ALLOW_LIVE_EXTERNAL_SENDS=true")

    monkeypatch.setattr("app.services.gmail_client.get_message", _unmocked_gmail_call)
    monkeypatch.setattr("app.services.gmail_client.send_message", _unmocked_gmail_call)
    monkeypatch.setattr("app.services.gmail_client.trash_message", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.services.ai_reply_service.generate_reply_draft",
        lambda message, invoice=None: "[test default — no real OpenAI call was made]",
    )

_FAKE_ADMIN_USER = {
    "id": "99999999-9999-9999-9999-999999999999",
    "full_name": "Test Admin",
    "email": "admin@test.omega",
    "role": "admin",
    "is_active": True,
}


def _ensure_fake_admin_user_row(supabase) -> bool:
    """Phase 3 introduced the first real-DB write that persists the overridden
    admin's id as a genuine foreign key (app_settings.updated_by) — Postgres
    enforces that FK even though tests/fake_supabase.py never did, so a
    dangling, made-up id 500s with a real constraint violation. Insert a real
    row so it's never dangling. Returns True if this call created it (so
    teardown knows it's safe to remove)."""
    existing = supabase.table("users").select("id").eq("id", _FAKE_ADMIN_USER["id"]).limit(1).execute()
    if existing.data:
        return False
    supabase.table("users").insert(
        {
            "id": _FAKE_ADMIN_USER["id"],
            "full_name": _FAKE_ADMIN_USER["full_name"],
            "email": _FAKE_ADMIN_USER["email"],
            "role": _FAKE_ADMIN_USER["role"],
            "is_active": True,
            "password_hash": auth_service.hash_password("not-a-real-login-this-id-is-override-only"),
        }
    ).execute()
    return True


@pytest.fixture(scope="module")
def run_id() -> str:
    return RUN_ID


@pytest.fixture(scope="module")
def real_env():
    """Yields (TestClient, created) where `created` is a registry the tests
    populate with IDs/codes as they create rows, so teardown knows what to
    remove. Cloudinary calls are stubbed, same as tests/conftest.py's `client`
    fixture, since this suite is about proving Supabase writes/reads, not
    exercising the Cloudinary integration."""
    supabase = get_supabase()
    created = {"party_ids": [], "item_codes": []}
    created_fake_admin_row = _ensure_fake_admin_user_row(supabase)

    patches = [
        patch(
            "app.services.cloudinary_client.upload_item_image",
            lambda file_bytes, item_code: (f"https://cdn.example.com/{item_code}.jpg", f"omega/{item_code}"),
        ),
        patch("app.services.cloudinary_client.delete_item_image", lambda public_id: None),
        patch(
            "app.routers.inventory.upload_item_image",
            lambda file_bytes, item_code: (f"https://cdn.example.com/{item_code}.jpg", f"omega/{item_code}"),
        ),
        patch("app.routers.inventory.delete_item_image", lambda public_id: None),
    ]
    for p in patches:
        p.start()

    # This suite proves real Supabase reads/writes, not the auth layer (that's
    # tests/integration/test_auth.py's job) — same dependency-override approach
    # as tests/conftest.py's `client` fixture, so these real-DB calls run as an
    # authenticated Admin without a real login round trip.
    app.dependency_overrides[get_current_user] = lambda: _FAKE_ADMIN_USER
    app.dependency_overrides[require_admin] = lambda: _FAKE_ADMIN_USER

    client = TestClient(app)

    try:
        yield client, created
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(require_admin, None)
        for p in patches:
            p.stop()
        # Null out any FK reference before removing the row it points to
        # (app_settings.updated_by has no ON DELETE clause -> RESTRICT).
        supabase.table("app_settings").update({"updated_by": None}).eq(
            "updated_by", _FAKE_ADMIN_USER["id"]
        ).execute()
        if created_fake_admin_row:
            supabase.table("users").delete().eq("id", _FAKE_ADMIN_USER["id"]).execute()
        _cleanup(supabase, created)


def _cleanup(supabase, created: dict) -> None:
    """FK-safe teardown. invoice_line_items/purchase_line_items cascade off
    customer_ledgers/purchases (ON DELETE CASCADE, schema_phase2.sql), so
    deleting the header rows first is sufficient — then inventory_items,
    then parties last (customer_ledgers.party_id is ON DELETE RESTRICT)."""
    for party_id in created["party_ids"]:
        supabase.table("customer_ledgers").delete().eq("party_id", party_id).execute()
        supabase.table("purchases").delete().eq("party_id", party_id).execute()
        supabase.table("expenses").delete().eq("party_id", party_id).execute()

    for item_code in created["item_codes"]:
        supabase.table("inventory_items").delete().eq("item_code", item_code).execute()

    for party_id in created["party_ids"]:
        supabase.table("parties").delete().eq("id", party_id).execute()
