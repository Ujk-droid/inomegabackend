"""Section 9.2 — PDF generation, Email dispatch, WhatsApp link, Duplicate
reprint. External calls (thumbnail fetch, Cloudinary upload, SMTP) are
monkeypatched, same convention as conftest.py's image-upload patches."""

import pytest


@pytest.fixture
def _sent_emails():
    return []


@pytest.fixture(autouse=True)
def _patch_dispatch_externals(monkeypatch, _sent_emails):
    monkeypatch.setattr("app.services.pdf_service._fetch_thumbnail", lambda url: None)
    monkeypatch.setattr(
        "app.services.cloudinary_client.upload_invoice_pdf",
        lambda pdf_bytes, invoice_no, duplicate=False: (
            f"https://cdn.example.com/invoices/{invoice_no}{'-duplicate' if duplicate else ''}.pdf",
            f"omega/invoices/{invoice_no}",
        ),
    )

    def _fake_send_email(to_email, subject, body, attachment=None):
        _sent_emails.append({"to_email": to_email, "subject": subject, "body": body, "attachment": attachment})

    monkeypatch.setattr("app.services.email_service.send_email", _fake_send_email)


def _finalize_invoice(client, party_id, item_code, qty):
    draft = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": qty}],
            "transaction_date": "2026-07-23",
        },
    )
    assert draft.status_code == 201, draft.text
    invoice_id = draft.json()["id"]
    finalize = client.post(f"/api/v1/invoices/{invoice_id}/finalize")
    assert finalize.status_code == 200, finalize.text
    return finalize.json()


def test_generate_share_email_and_whatsapp_link_on_an_approved_invoice(client, item_code, _sent_emails):
    party = client.post(
        "/api/v1/parties",
        json={
            "party_name": "United Scale Ijtibah With Contact Info",
            "party_type": "customer",
            "email": "customer@example.com",
            "phone": "0333-2218892",
        },
    )
    assert party.status_code == 201
    party_id = party.json()["id"]

    invoice = _finalize_invoice(client, party_id, item_code, qty=1)  # 12,300 — under threshold, auto-approved
    assert invoice["approval_status"] == "approved"
    invoice_id = invoice["id"]

    generate = client.post(f"/api/v1/invoices/{invoice_id}/generate")
    assert generate.status_code == 200
    assert generate.json()["pdf_url"].endswith(".pdf")

    email = client.post(f"/api/v1/invoices/{invoice_id}/share-email")
    assert email.status_code == 200
    assert email.json()["status"] == "sent"

    # Real PDF bytes attached, not just a link in the body — the party's
    # own email on file is used since no override was given.
    assert len(_sent_emails) == 1
    sent = _sent_emails[0]
    assert sent["to_email"] == "customer@example.com"
    assert sent["attachment"] is not None
    filename, pdf_bytes = sent["attachment"]
    assert filename == f"Invoice-{invoice['invoice_no']}.pdf"
    assert pdf_bytes.startswith(b"%PDF-")

    whatsapp = client.get(f"/api/v1/invoices/{invoice_id}/whatsapp-link")
    assert whatsapp.status_code == 200
    assert whatsapp.json()["whatsapp_url"].startswith("https://wa.me/")


def test_share_email_to_email_override_takes_priority_over_party_email(client, item_code, _sent_emails):
    party = client.post(
        "/api/v1/parties",
        json={
            "party_name": "Party With Stale Email",
            "party_type": "customer",
            "email": "stale@example.com",
            "phone": "0333-2218892",
        },
    )
    assert party.status_code == 201
    party_id = party.json()["id"]

    invoice = _finalize_invoice(client, party_id, item_code, qty=1)
    invoice_id = invoice["id"]

    email = client.post(f"/api/v1/invoices/{invoice_id}/share-email", json={"to_email": "override@example.com"})
    assert email.status_code == 200
    assert _sent_emails[0]["to_email"] == "override@example.com"


def test_share_email_fails_clearly_when_no_email_available_anywhere(client, item_code):
    party = client.post(
        "/api/v1/parties", json={"party_name": "Party With No Email", "party_type": "customer"}
    )
    assert party.status_code == 201
    party_id = party.json()["id"]

    invoice = _finalize_invoice(client, party_id, item_code, qty=1)
    invoice_id = invoice["id"]

    email = client.post(f"/api/v1/invoices/{invoice_id}/share-email")
    assert email.status_code == 502
    assert "no email" in email.json()["detail"].lower()


def test_dispatch_is_blocked_until_human_gate_approval(client, party_id, item_code):
    invoice = _finalize_invoice(client, party_id, item_code, qty=15)  # 184,500 — Invoice #2127's own case
    assert invoice["approval_status"] == "pending"
    invoice_id = invoice["id"]

    assert client.post(f"/api/v1/invoices/{invoice_id}/generate").status_code == 403
    assert client.post(f"/api/v1/invoices/{invoice_id}/share-email").status_code == 403
    assert client.get(f"/api/v1/invoices/{invoice_id}/whatsapp-link").status_code == 403
    assert client.post(f"/api/v1/invoices/{invoice_id}/reprint").status_code == 403

    approve = client.post(f"/api/v1/invoices/{invoice_id}/approve")
    assert approve.status_code == 200

    assert client.post(f"/api/v1/invoices/{invoice_id}/generate").status_code == 200


def test_reprint_gets_a_separate_duplicate_asset_and_leaves_the_original_untouched(client, party_id, item_code):
    invoice = _finalize_invoice(client, party_id, item_code, qty=1)
    invoice_id = invoice["id"]

    original = client.post(f"/api/v1/invoices/{invoice_id}/generate")
    original_url = original.json()["pdf_url"]

    reprint = client.post(f"/api/v1/invoices/{invoice_id}/reprint")
    assert reprint.status_code == 200
    assert reprint.json()["pdf_url"] != original_url
    assert "duplicate" in reprint.json()["pdf_url"]

    fetched = client.get(f"/api/v1/invoices/{invoice_id}")
    assert fetched.json()["id"] == invoice_id  # sanity: original invoice still fetchable, untouched
