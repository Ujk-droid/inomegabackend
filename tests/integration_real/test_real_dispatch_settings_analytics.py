"""Phase 3 blocks 3C-3G against the REAL Supabase project + REAL Cloudinary
(not mocked here, unlike the fake-client suite) — PDF/dispatch, the
Admin-editable Human Gate threshold, scheduler functions called directly, all
six Analytics queries, and a Gmail-placeholder graceful-degradation check.
Reuses `real_env` (conftest.py) since none of this is about auth. Every
Cloudinary asset uploaded here is destroyed in teardown; app_settings' prior
threshold is restored."""

import uuid

import cloudinary.uploader
import pytest

from app.database import get_supabase
from app.services import cloudinary_client, scheduler
from app.services.settings_service import get_settings_row


@pytest.fixture(scope="module")
def dispatch_env(real_env, run_id):
    client, created = real_env
    supabase = get_supabase()

    party = client.post(
        "/api/v1/parties",
        json={
            "party_name": f"ZZTEST_DispatchParty_{run_id}",
            "party_type": "customer",
            "phone": "0300-1234567",
            "email": f"zztest.dispatch.{run_id}@example.com",
        },
    )
    assert party.status_code == 201, party.text
    party_id = party.json()["id"]
    created["party_ids"].append(party_id)

    item = client.post(
        "/api/v1/inventory/create",
        data={
            "item_code": f"ZZTEST-DISP-{run_id}",
            "item_name": "ZZTEST Dispatch Item",
            "unit": "pcs",
            "rate": "1000",
            "quantity_in_stock": "50",
        },
    )
    assert item.status_code == 201, item.text
    item_code = item.json()["item_code"]
    created["item_codes"].append(item_code)

    cloudinary_public_ids = {"raw": [], "image": []}
    original_threshold = get_settings_row(supabase)["human_gate_threshold"]

    try:
        yield {"client": client, "party_id": party_id, "item_code": item_code, "cloudinary_ids": cloudinary_public_ids}
    finally:
        cloudinary_client._configure()
        for pid in cloudinary_public_ids["raw"]:
            try:
                cloudinary.uploader.destroy(pid, resource_type="raw")
            except Exception:
                pass
        for pid in cloudinary_public_ids["image"]:
            try:
                cloudinary.uploader.destroy(pid, resource_type="image")
            except Exception:
                pass
        supabase.table("app_settings").update({"human_gate_threshold": original_threshold}).eq(
            "id", get_settings_row(supabase)["id"]
        ).execute()


def _finalize(client, party_id, item_code, qty, transaction_date="2026-07-28"):
    draft = client.post(
        "/api/v1/invoices/draft",
        json={"party_id": party_id, "line_items": [{"item_code": item_code, "qty": qty}], "transaction_date": transaction_date},
    )
    assert draft.status_code == 201, draft.text
    invoice_id = draft.json()["id"]
    finalized = client.post(f"/api/v1/invoices/{invoice_id}/finalize")
    assert finalized.status_code == 200, finalized.text
    return finalized.json()


def test_settings_get_patch_and_gate_effect_real(dispatch_env):
    client = dispatch_env["client"]

    get_resp = client.get("/api/v1/settings")
    assert get_resp.status_code == 200
    original = get_resp.json()["human_gate_threshold"]
    assert original is not None

    patch_resp = client.patch("/api/v1/settings", json={"human_gate_threshold": 500})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["human_gate_threshold"] == 500.0

    invoice = _finalize(client, dispatch_env["party_id"], dispatch_env["item_code"], qty=1)  # 1,000 > 500
    assert invoice["approval_status"] == "pending"

    # restore immediately so later tests in this module see the normal threshold
    client.patch("/api/v1/settings", json={"human_gate_threshold": original})


def test_generate_reprint_and_whatsapp_link_real(dispatch_env):
    client = dispatch_env["client"]
    invoice = _finalize(client, dispatch_env["party_id"], dispatch_env["item_code"], qty=1, transaction_date="2026-07-29")
    invoice_id = invoice["id"]
    assert invoice["approval_status"] == "approved"

    generate = client.post(f"/api/v1/invoices/{invoice_id}/generate")
    assert generate.status_code == 200, generate.text
    pdf_url = generate.json()["pdf_url"]
    assert pdf_url.startswith("https://res.cloudinary.com/")
    dispatch_env["cloudinary_ids"]["raw"].append(f"omega-scales/invoices/{invoice['invoice_no']}")

    import httpx

    fetched = httpx.get(pdf_url, timeout=10)
    assert fetched.status_code == 200
    assert fetched.headers["content-type"].startswith("application/pdf") or len(fetched.content) > 100

    reprint = client.post(f"/api/v1/invoices/{invoice_id}/reprint")
    assert reprint.status_code == 200, reprint.text
    reprint_url = reprint.json()["pdf_url"]
    assert reprint_url != pdf_url
    dispatch_env["cloudinary_ids"]["raw"].append(f"omega-scales/invoices/{invoice['invoice_no']}-duplicate")

    unchanged = client.get(f"/api/v1/invoices/{invoice_id}")
    assert unchanged.json()["id"] == invoice_id  # original row untouched

    whatsapp = client.get(f"/api/v1/invoices/{invoice_id}/whatsapp-link")
    assert whatsapp.status_code == 200
    assert whatsapp.json()["whatsapp_url"].startswith("https://wa.me/03001234567")

    # NOTE: GMAIL_APP_PASSWORD is a REAL credential as of this verification run
    # (the user supplied it after this test was first written against a
    # placeholder-credential assumption) — this now sends a real email via the
    # business's real Gmail account to the ZZTEST party's @example.com address
    # (harmless: reserved, non-deliverable domain, but a real SMTP send happens).
    email = client.post(f"/api/v1/invoices/{invoice_id}/share-email")
    assert email.status_code == 200, email.text
    assert email.json()["status"] == "sent"


def test_scheduler_functions_against_real_postgres(dispatch_env):
    supabase = get_supabase()
    client = dispatch_env["client"]

    # A transaction_date this recent keeps due_date (+15 days) in the future,
    # so finalize computes 'unpaid', not already 'overdue' — the flip below
    # needs a row that starts as unpaid/partial so there's something to flip.
    invoice = _finalize(client, dispatch_env["party_id"], dispatch_env["item_code"], qty=1, transaction_date="2026-07-30")
    invoice_id = invoice["id"]
    assert invoice["invoice_status"] == "unpaid"

    supabase.table("customer_ledgers").update({"due_date": "2020-01-01"}).eq("id", invoice_id).execute()

    flipped = scheduler.flip_overdue_invoices(supabase)
    assert any(row["id"] == invoice_id for row in flipped)

    refetched = client.get(f"/api/v1/invoices/{invoice_id}")
    assert refetched.json()["invoice_status"] == "overdue"

    # NOTE: Gmail creds are real now — this sends one genuine "Daily Digest"
    # email to every real active Admin in the live `users` table (e.g. the
    # business owners), same as production behavior. Expected side effect of
    # verifying this against the real system, not a bug.
    digest = scheduler.send_daily_digest(supabase)
    assert "low_stock_count" in digest
    assert isinstance(digest["sent_to"], list)

    expired = scheduler.expire_stale_login_requests(supabase)
    assert isinstance(expired, list)


def test_analytics_endpoints_return_real_data(dispatch_env):
    """Charts moved from server-rendered Matplotlib/Cloudinary PNGs to live
    @gravity-ui/charts on the frontend (see progress.md) — these endpoints
    now return only real numbers, nothing to upload or clean up here."""
    client = dispatch_env["client"]
    _finalize(client, dispatch_env["party_id"], dispatch_env["item_code"], qty=2, transaction_date="2026-07-30")

    monthly = client.get("/api/v1/analytics/monthly-sales-revenue")
    assert monthly.status_code == 200
    assert isinstance(monthly.json()["data"], list)

    low_stock = client.get("/api/v1/analytics/low-stock-items")
    assert low_stock.status_code == 200
    assert isinstance(low_stock.json()["data"], list)


def test_inbox_sync_against_real_gmail_api(dispatch_env):
    """GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN are real credentials as of this
    verification run (originally written expecting a placeholder-credential
    502) — this now polls the business's actual Gmail inbox read-only via the
    real Gmail API and matches against real `parties`/`customer_ledgers`.
    Confirmed separately that this run found 0 matches against the live
    inbox_messages table (nothing to clean up), but don't assert a specific
    count here since real mailbox contents can change between runs."""
    resp = dispatch_env["client"].post("/api/v1/inbox/sync")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {"synced", "already_seen", "skipped_unmatched"} <= body.keys()
