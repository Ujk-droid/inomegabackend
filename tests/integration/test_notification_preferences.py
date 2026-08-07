"""Screen 10 Settings' Notification preferences — per-user GET/PATCH, and the
three real send paths (daily digest, Human Gate pending, Staff login request)
that now check them before emailing."""

from datetime import date

from app.services import notification_preferences_service, scheduler
from tests.conftest import FAKE_ADMIN_USER


def test_get_preferences_defaults_to_all_on_when_no_row_exists(client):
    resp = client.get("/api/v1/notification-preferences")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "low_stock_digest": True,
        "human_gate_approval": True,
        "login_approval_request": True,
    }


def test_patch_preferences_creates_a_row_and_persists_partial_updates(client, fake_supabase):
    resp = client.patch("/api/v1/notification-preferences", json={"low_stock_digest": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["low_stock_digest"] is False
    assert body["human_gate_approval"] is True  # untouched field keeps its default
    assert body["login_approval_request"] is True

    # A second, different partial update doesn't clobber the first change.
    resp2 = client.patch("/api/v1/notification-preferences", json={"human_gate_approval": False})
    assert resp2.json() == {
        "low_stock_digest": False,
        "human_gate_approval": False,
        "login_approval_request": True,
    }

    refetched = client.get("/api/v1/notification-preferences").json()
    assert refetched == resp2.json()
    assert len(fake_supabase.tables["notification_preferences"]) == 1  # one row, updated in place


def test_daily_digest_skips_an_admin_who_disabled_low_stock_digest(fake_supabase, monkeypatch):
    sent = []
    monkeypatch.setattr(scheduler, "send_email", lambda to, subject, body: sent.append(to))
    fake_supabase.tables["notification_preferences"].append(
        {"user_id": FAKE_ADMIN_USER["id"], "low_stock_digest": False, "human_gate_approval": True, "login_approval_request": True}
    )

    result = scheduler.send_daily_digest(fake_supabase)

    assert result["sent_to"] == []
    assert sent == []


def test_daily_digest_sends_when_preference_is_left_default_on(fake_supabase, monkeypatch):
    sent = []
    monkeypatch.setattr(scheduler, "send_email", lambda to, subject, body: sent.append(to))

    result = scheduler.send_daily_digest(fake_supabase)

    assert result["sent_to"] == [FAKE_ADMIN_USER["email"]]
    assert sent == [FAKE_ADMIN_USER["email"]]


def test_finalize_notifies_admin_of_pending_invoice_by_default(client, fake_supabase, party_id, item_code, monkeypatch):
    sent = []
    monkeypatch.setattr("app.services.email_service.send_email", lambda to, subject, body, attachment=None: sent.append((to, subject)))

    draft = client.post(
        "/api/v1/invoices/draft",
        json={"party_id": party_id, "line_items": [{"item_code": item_code, "qty": 15, "rate": 12300}], "transaction_date": "2026-07-23"},
    )
    finalized = client.post(f"/api/v1/invoices/{draft.json()['id']}/finalize")
    assert finalized.json()["approval_status"] == "pending"

    assert len(sent) == 1
    assert sent[0][0] == FAKE_ADMIN_USER["email"]
    assert "approval" in sent[0][1].lower()


def test_finalize_skips_notification_when_human_gate_approval_disabled(client, fake_supabase, party_id, item_code, monkeypatch):
    sent = []
    monkeypatch.setattr("app.services.email_service.send_email", lambda to, subject, body, attachment=None: sent.append(to))
    fake_supabase.tables["notification_preferences"].append(
        {"user_id": FAKE_ADMIN_USER["id"], "low_stock_digest": True, "human_gate_approval": False, "login_approval_request": True}
    )

    draft = client.post(
        "/api/v1/invoices/draft",
        json={"party_id": party_id, "line_items": [{"item_code": item_code, "qty": 15, "rate": 12300}], "transaction_date": "2026-07-23"},
    )
    client.post(f"/api/v1/invoices/{draft.json()['id']}/finalize")

    assert sent == []


def test_finalize_below_threshold_never_notifies(client, fake_supabase, party_id, item_code, monkeypatch):
    sent = []
    monkeypatch.setattr("app.services.email_service.send_email", lambda to, subject, body, attachment=None: sent.append(to))

    draft = client.post(
        "/api/v1/invoices/draft",
        json={"party_id": party_id, "line_items": [{"item_code": item_code, "qty": 1, "rate": 100}], "transaction_date": "2026-07-23"},
    )
    finalized = client.post(f"/api/v1/invoices/{draft.json()['id']}/finalize")
    assert finalized.json()["approval_status"] == "approved"
    assert sent == []


def test_login_request_notification_skipped_when_admin_disabled_it(
    raw_client, fake_supabase, monkeypatch, seeded_staff, staff_password
):
    sent = []
    monkeypatch.setattr("app.services.email_service.send_email", lambda to, subject, body, attachment=None: sent.append(to))
    fake_supabase.tables["notification_preferences"].append(
        {"user_id": FAKE_ADMIN_USER["id"], "low_stock_digest": True, "human_gate_approval": True, "login_approval_request": False}
    )

    resp = raw_client.post("/api/v1/auth/login", json={"email": seeded_staff["email"], "password": staff_password})
    assert resp.json()["status"] == "pending"

    assert sent == []


def test_login_request_notification_sent_by_default(raw_client, fake_supabase, monkeypatch, seeded_staff, staff_password):
    sent = []
    monkeypatch.setattr("app.services.email_service.send_email", lambda to, subject, body, attachment=None: sent.append(to))

    resp = raw_client.post("/api/v1/auth/login", json={"email": seeded_staff["email"], "password": staff_password})
    assert resp.json()["status"] == "pending"

    assert sent == [FAKE_ADMIN_USER["email"]]
