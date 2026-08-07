"""Section 16.5 — Delivery Challan: simpler PDF (no pricing), generated once
per finalized invoice, marked with a delivery date once actually delivered."""

import pytest


@pytest.fixture(autouse=True)
def _patch_dispatch_externals(monkeypatch):
    monkeypatch.setattr("app.services.pdf_service._fetch_thumbnail", lambda url: None)
    monkeypatch.setattr(
        "app.services.cloudinary_client.upload_delivery_challan_pdf",
        lambda pdf_bytes, challan_no: (f"https://res.cloudinary.com/fake/{challan_no}.pdf", f"omega-scales/delivery-challans/{challan_no}"),
    )


def _finalized_invoice(client, party_id, item_code):
    draft = client.post(
        "/api/v1/invoices/draft",
        json={"party_id": party_id, "line_items": [{"item_code": item_code, "qty": 2, "rate": 500}], "transaction_date": "2026-07-30"},
    ).json()
    return client.post(f"/api/v1/invoices/{draft['id']}/finalize").json()


def test_generate_challan_for_finalized_invoice(client, party_id, item_code):
    invoice = _finalized_invoice(client, party_id, item_code)

    resp = client.post(f"/api/v1/invoices/{invoice['id']}/delivery-challan")
    assert resp.status_code == 201
    body = resp.json()
    assert body["invoice_id"] == invoice["id"]
    assert body["challan_no"] is not None
    assert body["pdf_cloudinary_url"].endswith(".pdf")
    assert body["delivered_at"] is None

    log = client.get("/api/v1/activity-log").json()
    assert any(entry["action"] == "delivery_challan_generated" for entry in log)


def test_challan_blocked_on_a_draft_invoice(client, party_id, item_code):
    draft = client.post(
        "/api/v1/invoices/draft",
        json={"party_id": party_id, "line_items": [{"item_code": item_code, "qty": 1, "rate": 500}], "transaction_date": "2026-07-30"},
    ).json()

    resp = client.post(f"/api/v1/invoices/{draft['id']}/delivery-challan")
    assert resp.status_code == 409


def test_challan_can_only_be_generated_once_per_invoice(client, party_id, item_code):
    invoice = _finalized_invoice(client, party_id, item_code)
    first = client.post(f"/api/v1/invoices/{invoice['id']}/delivery-challan")
    assert first.status_code == 201

    second = client.post(f"/api/v1/invoices/{invoice['id']}/delivery-challan")
    assert second.status_code == 409


def test_get_challan_for_invoice(client, party_id, item_code):
    invoice = _finalized_invoice(client, party_id, item_code)
    created = client.post(f"/api/v1/invoices/{invoice['id']}/delivery-challan").json()

    resp = client.get(f"/api/v1/invoices/{invoice['id']}/delivery-challan")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_get_challan_404s_when_none_exists(client, party_id, item_code):
    invoice = _finalized_invoice(client, party_id, item_code)
    resp = client.get(f"/api/v1/invoices/{invoice['id']}/delivery-challan")
    assert resp.status_code == 404


def test_mark_delivered(client, party_id, item_code):
    invoice = _finalized_invoice(client, party_id, item_code)
    challan = client.post(f"/api/v1/invoices/{invoice['id']}/delivery-challan").json()

    resp = client.post(f"/api/v1/delivery-challans/{challan['id']}/mark-delivered", json={"delivered_at": "2026-08-01"})
    assert resp.status_code == 200
    assert resp.json()["delivered_at"] == "2026-08-01"

    log = client.get("/api/v1/activity-log").json()
    assert any(entry["action"] == "delivery_challan_marked_delivered" for entry in log)


def test_mark_delivered_unknown_id_404s(client):
    resp = client.post(
        "/api/v1/delivery-challans/00000000-0000-0000-0000-000000000000/mark-delivered",
        json={"delivered_at": "2026-08-01"},
    )
    assert resp.status_code == 404
