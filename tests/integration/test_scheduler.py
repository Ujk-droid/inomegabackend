"""Section 7.1's second heartbeat (daily digest) + Section 5.3's deferred
overdue flip + Section 3.1's login-request expiry, exercised directly (not
through the real APScheduler, per the plan) against the fake Supabase client."""

from datetime import date

import pytest

from app.services import scheduler


@pytest.fixture(autouse=True)
def _redirect_progress_spine(monkeypatch, tmp_path):
    """scheduler._log_spine writes to progress.md unconditionally on every
    digest send — redirect it to a scratch file so running tests never edits
    the real project spine file."""
    monkeypatch.setattr(scheduler, "PROGRESS_FILE", tmp_path / "test-progress.md")


@pytest.fixture(autouse=True)
def _patch_email(monkeypatch):
    monkeypatch.setattr(scheduler, "send_email", lambda *a, **k: None)


def test_flip_overdue_invoices_flips_a_stale_unpaid_invoice(client, fake_supabase, party_id, item_code):
    draft = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": 1}],
            "transaction_date": str(date.today()),
        },
    )
    invoice_id = draft.json()["id"]
    finalized = client.post(f"/api/v1/invoices/{invoice_id}/finalize")
    assert finalized.json()["invoice_status"] == "unpaid"  # due_date is 15 days out — not overdue yet

    for row in fake_supabase.tables["customer_ledgers"]:
        if row["id"] == invoice_id:
            row["due_date"] = "2020-01-01"  # force it into the past

    flipped = scheduler.flip_overdue_invoices(fake_supabase)
    assert len(flipped) == 1
    assert flipped[0]["invoice_status"] == "overdue"

    fetched = client.get(f"/api/v1/invoices/{invoice_id}")
    assert fetched.json()["invoice_status"] == "overdue"


def test_flip_overdue_invoices_leaves_paid_invoices_alone(client, fake_supabase, party_id, item_code):
    draft = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": 1}],
            "transaction_date": str(date.today()),
            "received_at_sale": 12300,
        },
    )
    invoice_id = draft.json()["id"]
    finalized = client.post(f"/api/v1/invoices/{invoice_id}/finalize")
    assert finalized.json()["invoice_status"] == "paid"

    for row in fake_supabase.tables["customer_ledgers"]:
        if row["id"] == invoice_id:
            row["due_date"] = "2020-01-01"

    flipped = scheduler.flip_overdue_invoices(fake_supabase)
    assert flipped == []


def test_daily_digest_always_sends_even_with_nothing_to_report(fake_supabase):
    """Section 7.1: 'it always sends, even if the list is empty.'"""
    result = scheduler.send_daily_digest(fake_supabase)
    assert result["low_stock_count"] == 0
    assert result["overdue_count"] == 0


def test_daily_digest_reports_low_stock_items(fake_supabase):
    fake_supabase.tables["inventory_items"].append(
        {"id": "x1", "item_code": "LOW-1", "item_name": "Low Item", "quantity_in_stock": 2, "min_threshold": 5}
    )
    result = scheduler.send_daily_digest(fake_supabase)
    assert result["low_stock_count"] == 1


def test_manual_run_digest_endpoint_is_admin_only(raw_client, seeded_staff):
    from app.services import auth_service

    token = auth_service.create_access_token(seeded_staff["id"], seeded_staff["role"])
    raw_client.cookies.set("omega_session", token)
    resp = raw_client.post("/api/v1/internal/run-digest")
    assert resp.status_code == 403


def test_manual_run_digest_endpoint_works_for_admin(client):
    resp = client.post("/api/v1/internal/run-digest")
    assert resp.status_code == 200
    assert "low_stock_count" in resp.json()


def test_expire_stale_login_requests_delegates_to_login_gate_service(client, fake_supabase, seeded_staff, staff_password):
    from datetime import datetime, timedelta, timezone

    from app.services import login_gate_service

    pending = login_gate_service.create_pending_request(fake_supabase, seeded_staff["id"])
    stale = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    for row in fake_supabase.tables["login_requests"]:
        if row["id"] == pending["id"]:
            row["requested_at"] = stale

    expired = scheduler.expire_stale_login_requests(fake_supabase)
    assert len(expired) == 1
    assert expired[0]["status"] == "expired"
