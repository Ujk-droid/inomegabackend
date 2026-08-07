"""Purchase Builder's PDF endpoints, mirroring test_invoice_preview_pdf.py's
conventions: a live preview for an unsaved form, plus (unique to purchases,
since they have no draft/finalize split) a real-PDF-by-id endpoint for the
already-created bill, since 'Print & Save' should show the real assigned
purchase_bill_no, not the preview's 'DRAFT' placeholder."""

import pytest


@pytest.fixture(autouse=True)
def _patch_thumbnail_fetch(monkeypatch):
    monkeypatch.setattr("app.services.pdf_service._fetch_thumbnail", lambda url: None)


def test_preview_pdf_returns_a_real_pdf(client, supplier_id, item_code):
    resp = client.post(
        "/api/v1/purchases/preview-pdf",
        json={
            "party_id": supplier_id,
            "line_items": [{"item_code": item_code, "qty": 20, "rate": 9000}],
            "transaction_date": "2026-07-30",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")


def test_preview_pdf_persists_nothing(client, supplier_id, item_code, fake_supabase):
    client.post(
        "/api/v1/purchases/preview-pdf",
        json={
            "party_id": supplier_id,
            "line_items": [{"item_code": item_code, "qty": 2}],
            "transaction_date": "2026-07-30",
        },
    )
    assert fake_supabase.tables["purchases"] == []
    assert fake_supabase.tables["purchase_line_items"] == []


def test_preview_pdf_unknown_party_404s(client, item_code):
    resp = client.post(
        "/api/v1/purchases/preview-pdf",
        json={
            "party_id": "00000000-0000-0000-0000-000000000000",
            "line_items": [{"item_code": item_code, "qty": 1}],
            "transaction_date": "2026-07-30",
        },
    )
    assert resp.status_code == 404


def test_purchase_pdf_by_id_shows_real_bill_number(client, supplier_id, item_code):
    created = client.post(
        "/api/v1/purchases",
        json={
            "party_id": supplier_id,
            "line_items": [{"item_code": item_code, "qty": 20, "rate": 9000}],
            "transaction_date": "2026-07-30",
        },
    ).json()

    resp = client.get(f"/api/v1/purchases/{created['id']}/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")


def test_purchase_pdf_unknown_id_404s(client):
    resp = client.get("/api/v1/purchases/00000000-0000-0000-0000-000000000000/pdf")
    assert resp.status_code == 404
