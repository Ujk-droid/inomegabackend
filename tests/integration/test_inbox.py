"""Section 9.1 — Gmail Inbox sync (matching), list/read/reply/mark/delete, and
AI-drafted (never auto-sent) replies. Gmail/OpenAI calls are monkeypatched —
GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN are still .env placeholders by the user's
own choice (build now, wire real credentials later)."""

import pytest

from app.services import gmail_client


def _finalize_invoice(client, party_id, item_code, qty):
    draft = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": qty}],
            "transaction_date": "2026-07-23",
        },
    )
    invoice_id = draft.json()["id"]
    finalized = client.post(f"/api/v1/invoices/{invoice_id}/finalize")
    return finalized.json()


def _fake_get_message(message_id: str, fixtures: dict) -> dict:
    return fixtures[message_id]


@pytest.fixture
def matched_scenario(client, party_id, item_code, monkeypatch):
    # give the existing party_id fixture's party a matching email
    parties_resp = client.get("/api/v1/parties")
    party = next(p for p in parties_resp.json() if p["id"] == party_id)
    assert party["party_name"] == "United Scale Ijtibah"

    # party_id fixture doesn't set an email — patch it directly in the store instead
    invoice = _finalize_invoice(client, party_id, item_code, qty=1)
    invoice_no = invoice["invoice_no"]

    fixtures = {
        "msg1": {
            "gmail_message_id": "msg1",
            "gmail_thread_id": "thread1",
            "from_email": "Customer Name <matched-party@example.com>",
            "subject": "Question about my order",
            "snippet": "Hi, quick question about my last order.",
            "received_at_header": None,
        },
        "msg2": {
            "gmail_message_id": "msg2",
            "gmail_thread_id": "thread2",
            "from_email": "Someone Else <random@nowhere.com>",
            "subject": f"Re: Invoice #{invoice_no} payment",
            "snippet": "When is this due?",
            "received_at_header": None,
        },
        "msg3": {
            "gmail_message_id": "msg3",
            "gmail_thread_id": "thread3",
            "from_email": "Nobody <nobody@nowhere.com>",
            "subject": "Unrelated newsletter",
            "snippet": "50% off scales this week!",
            "received_at_header": None,
        },
    }

    monkeypatch.setattr(gmail_client, "list_message_ids", lambda query, max_results=25: list(fixtures.keys()))
    monkeypatch.setattr(gmail_client, "get_message", lambda message_id: _fake_get_message(message_id, fixtures))

    return {"invoice_no": invoice_no}


def test_sync_only_keeps_matched_messages(client, fake_supabase, matched_scenario):
    # give the party a matching email so msg1 matches by party
    for row in fake_supabase.tables["parties"]:
        row["email"] = "matched-party@example.com"

    resp = client.post("/api/v1/inbox/sync")
    assert resp.status_code == 200
    body = resp.json()
    assert body["synced"] == 2
    assert body["skipped_unmatched"] == 1

    listed = client.get("/api/v1/inbox")
    assert listed.status_code == 200
    assert len(listed.json()) == 2
    subjects = {m["subject"] for m in listed.json()}
    assert "Unrelated newsletter" not in subjects


def test_sync_is_idempotent_on_rerun(client, fake_supabase, matched_scenario):
    for row in fake_supabase.tables["parties"]:
        row["email"] = "matched-party@example.com"

    client.post("/api/v1/inbox/sync")
    second = client.post("/api/v1/inbox/sync")
    assert second.json()["synced"] == 0
    assert second.json()["already_seen"] == 2


def test_mark_read_reply_and_delete(client, fake_supabase, matched_scenario, monkeypatch):
    for row in fake_supabase.tables["parties"]:
        row["email"] = "matched-party@example.com"
    client.post("/api/v1/inbox/sync")

    message_id = client.get("/api/v1/inbox").json()[0]["id"]

    mark = client.patch(f"/api/v1/inbox/{message_id}", json={"is_read": True})
    assert mark.status_code == 200
    assert mark.json()["is_read"] is True

    sent = {}
    monkeypatch.setattr(
        gmail_client, "send_message", lambda to, subject, body, thread_id=None: sent.update(to=to, body=body) or "sent-id"
    )
    reply = client.post(f"/api/v1/inbox/{message_id}/reply", json={"body": "Thanks for reaching out!"})
    assert reply.status_code == 200
    assert "Thanks for reaching out!" in sent["body"]

    monkeypatch.setattr(gmail_client, "trash_message", lambda message_id: None)
    deleted = client.delete(f"/api/v1/inbox/{message_id}")
    assert deleted.status_code == 204

    after_delete = client.get("/api/v1/inbox")
    assert all(m["id"] != message_id for m in after_delete.json())


def test_generate_ai_reply_never_sends_only_drafts(client, fake_supabase, matched_scenario, monkeypatch):
    for row in fake_supabase.tables["parties"]:
        row["email"] = "matched-party@example.com"
    client.post("/api/v1/inbox/sync")
    message_id = client.get("/api/v1/inbox").json()[0]["id"]

    monkeypatch.setattr("app.services.ai_reply_service.generate_reply_draft", lambda message, invoice=None: "Draft: thanks!")
    sent_calls = []
    monkeypatch.setattr(
        gmail_client, "send_message", lambda *a, **k: sent_calls.append(a) or "sent-id"
    )

    draft = client.post(f"/api/v1/inbox/{message_id}/generate-reply")
    assert draft.status_code == 200
    assert draft.json()["draft"] == "Draft: thanks!"
    assert sent_calls == []  # a draft must never itself trigger a send


def test_reply_attaches_invoice_pdf_link_when_requested(client, fake_supabase, matched_scenario, monkeypatch):
    for row in fake_supabase.tables["parties"]:
        row["email"] = "matched-party@example.com"
    client.post("/api/v1/inbox/sync")
    invoice_no = matched_scenario["invoice_no"]

    for row in fake_supabase.tables["customer_ledgers"]:
        if row.get("invoice_no") == invoice_no:
            row["pdf_cloudinary_url"] = "https://cdn.example.com/invoices/test.pdf"

    invoice_message = next(m for m in client.get("/api/v1/inbox").json() if m["related_invoice_no"] == invoice_no)

    sent = {}
    monkeypatch.setattr(
        gmail_client, "send_message", lambda to, subject, body, thread_id=None: sent.update(body=body) or "sent-id"
    )
    reply = client.post(
        f"/api/v1/inbox/{invoice_message['id']}/reply",
        json={"body": "Here you go.", "attach_invoice_no": invoice_no},
    )
    assert reply.status_code == 200
    assert "https://cdn.example.com/invoices/test.pdf" in sent["body"]


def test_sync_is_admin_only(raw_client, seeded_staff):
    from app.services import auth_service

    token = auth_service.create_access_token(seeded_staff["id"], seeded_staff["role"])
    raw_client.cookies.set("omega_session", token)
    resp = raw_client.post("/api/v1/inbox/sync")
    assert resp.status_code == 403
