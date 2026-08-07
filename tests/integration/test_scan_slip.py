"""Section 5.4.K — Scan Slip. OpenAI Vision and the Cloudinary upload are
both mocked (conftest.py's global safety net covers this by default; tests
below override with per-test extracted items where the exact content matters)."""

import io


def _mock_extraction(monkeypatch, items):
    monkeypatch.setattr("app.services.scan_slip_service._extract_line_items", lambda image_url: items)


def test_scan_slip_high_confidence_exact_match(client, item_code, monkeypatch):
    _mock_extraction(
        monkeypatch,
        [{"description": "Platform 400x400 SS Top Cap.150Kg 10g (MK-03)", "qty": 15, "rate": 12300}],
    )
    resp = client.post(
        "/api/v1/invoices/scan-slip",
        files={"file": ("slip.jpg", io.BytesIO(b"fake-image-bytes"), "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scan_slip_cloudinary_url"] == "https://cdn.example.com/scan-slips/test.jpg"
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["confidence"] == "high"
    assert item["matched_item_code"] == item_code
    assert item["qty"] == 15
    assert item["rate"] == 12300


def test_scan_slip_low_confidence_partial_match(client, item_code, monkeypatch):
    _mock_extraction(monkeypatch, [{"description": "15 platform scales", "qty": 15, "rate": None}])
    resp = client.post(
        "/api/v1/invoices/scan-slip",
        files={"file": ("slip.jpg", io.BytesIO(b"fake-image-bytes"), "image/jpeg")},
    )
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["confidence"] == "low"
    assert item["matched_item_code"] == item_code
    assert item["rate"] is None


def test_scan_slip_no_match_for_unrelated_description(client, item_code, monkeypatch):
    _mock_extraction(monkeypatch, [{"description": "load cell 5 ton", "qty": 1, "rate": None}])
    resp = client.post(
        "/api/v1/invoices/scan-slip",
        files={"file": ("slip.jpg", io.BytesIO(b"fake-image-bytes"), "image/jpeg")},
    )
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["confidence"] == "none"
    assert item["matched_item_code"] is None
    assert item["matched_item_name"] is None


def test_scan_slip_defaults_qty_to_one_when_missing(client, item_code, monkeypatch):
    _mock_extraction(monkeypatch, [{"description": "some item with no qty stated"}])
    resp = client.post(
        "/api/v1/invoices/scan-slip",
        files={"file": ("slip.jpg", io.BytesIO(b"fake-image-bytes"), "image/jpeg")},
    )
    assert resp.status_code == 200
    assert resp.json()["items"][0]["qty"] == 1


def test_scan_slip_empty_slip_returns_empty_items(client, item_code, monkeypatch):
    _mock_extraction(monkeypatch, [])
    resp = client.post(
        "/api/v1/invoices/scan-slip",
        files={"file": ("slip.jpg", io.BytesIO(b"fake-image-bytes"), "image/jpeg")},
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_scan_slip_rejects_non_image_upload(client):
    resp = client.post(
        "/api/v1/invoices/scan-slip",
        files={"file": ("notes.txt", io.BytesIO(b"not an image"), "text/plain")},
    )
    assert resp.status_code == 400


def test_scan_slip_ai_error_becomes_502(client, monkeypatch):
    def _boom(image_url):
        from app.services.scan_slip_service import ScanSlipError

        raise ScanSlipError("The AI's response could not be parsed")

    monkeypatch.setattr("app.services.scan_slip_service._extract_line_items", _boom)
    resp = client.post(
        "/api/v1/invoices/scan-slip",
        files={"file": ("slip.jpg", io.BytesIO(b"fake-image-bytes"), "image/jpeg")},
    )
    assert resp.status_code == 502


def test_draft_create_persists_scan_slip_url(client, party_id, item_code):
    resp = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": 2}],
            "transaction_date": "2026-07-23",
            "scan_slip_cloudinary_url": "https://cdn.example.com/scan-slips/abc123.jpg",
        },
    )
    assert resp.status_code == 201
    invoice_id = resp.json()["id"]
    assert resp.json()["scan_slip_cloudinary_url"] == "https://cdn.example.com/scan-slips/abc123.jpg"

    fetched = client.get(f"/api/v1/invoices/{invoice_id}")
    assert fetched.json()["scan_slip_cloudinary_url"] == "https://cdn.example.com/scan-slips/abc123.jpg"


def test_draft_create_without_scan_slip_is_null(client, party_id, item_code):
    resp = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": 1}],
            "transaction_date": "2026-07-23",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["scan_slip_cloudinary_url"] is None
