"""Section 9.2's 'live PDF preview' — a read-only render for an unsaved draft.
No thumbnail/network calls should ever leave the process for this endpoint,
same convention as test_invoice_dispatch.py."""

import pytest


@pytest.fixture(autouse=True)
def _patch_thumbnail_fetch(monkeypatch):
    monkeypatch.setattr("app.services.pdf_service._fetch_thumbnail", lambda url: None)


def test_preview_pdf_returns_a_real_pdf(client, party_id, item_code):
    resp = client.post(
        "/api/v1/invoices/preview-pdf",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": 15, "rate": 12300}],
            "transaction_date": "2026-07-23",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")
    assert len(resp.content) > 500


def test_preview_pdf_persists_nothing(client, party_id, item_code, fake_supabase):
    client.post(
        "/api/v1/invoices/preview-pdf",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": 2}],
            "transaction_date": "2026-07-23",
        },
    )
    assert fake_supabase.tables["customer_ledgers"] == []
    assert fake_supabase.tables["invoice_line_items"] == []


def test_preview_pdf_unknown_party_404s(client, item_code):
    resp = client.post(
        "/api/v1/invoices/preview-pdf",
        json={
            "party_id": "00000000-0000-0000-0000-000000000000",
            "line_items": [{"item_code": item_code, "qty": 1}],
            "transaction_date": "2026-07-23",
        },
    )
    assert resp.status_code == 404


def test_preview_pdf_unknown_item_404s(client, party_id):
    resp = client.post(
        "/api/v1/invoices/preview-pdf",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": "NOT-A-REAL-CODE", "qty": 1}],
            "transaction_date": "2026-07-23",
        },
    )
    assert resp.status_code == 404


def test_preview_pdf_math_matches_finalize_math(client, party_id, item_code, monkeypatch):
    """Same 15 x 12,300 = 184,500 case as the Human Gate acceptance test
    (Section 7.4) — the preview's computed totals must match what finalize
    would actually produce, not just 'some PDF came back'."""
    captured = {}
    real_build = __import__("app.services.pdf_service", fromlist=["build_invoice_pdf"]).build_invoice_pdf

    def _capture(invoice, party, line_items, items_by_code, **kwargs):
        captured.update(invoice)
        return real_build(invoice, party, line_items, items_by_code, **kwargs)

    monkeypatch.setattr("app.services.invoice_dispatch_service.pdf_service.build_invoice_pdf", _capture)

    resp = client.post(
        "/api/v1/invoices/preview-pdf",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": 15, "rate": 12300}],
            "discount_amount": 0,
            "transaction_date": "2026-07-23",
            "received_at_sale": 0,
        },
    )
    assert resp.status_code == 200
    assert captured["total_amount"] == 184500
    assert captured["previous_balance"] == 0
    assert captured["current_balance"] == 184500
    assert captured["invoice_no"] is None
