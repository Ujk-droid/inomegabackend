"""Section 8 — the six Analytics queries. No Cloudinary/chart rendering left
here — every endpoint returns real numbers only, rendered live on the
frontend via @gravity-ui/charts (see progress.md); the underlying data is
asserted directly."""


def _finalize_invoice(client, party_id, item_code, qty, transaction_date="2026-04-14"):
    draft = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": qty}],
            "transaction_date": transaction_date,
        },
    )
    invoice_id = draft.json()["id"]
    return client.post(f"/api/v1/invoices/{invoice_id}/finalize").json()


def test_monthly_sales_revenue_reflects_a_finalized_sale(client, party_id, item_code):
    invoice = _finalize_invoice(client, party_id, item_code, qty=1, transaction_date="2026-04-14")
    resp = client.get("/api/v1/analytics/monthly-sales-revenue")
    assert resp.status_code == 200
    body = resp.json()
    april = next(d for d in body["data"] if d["month"] == "2026-04")
    assert april["revenue"] == float(invoice["total_amount"])


def test_monthly_sales_revenue_excludes_draft_invoices(client, party_id, item_code):
    invoice = _finalize_invoice(client, party_id, item_code, qty=1, transaction_date="2026-04-14")

    draft_only = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": 99}],
            "transaction_date": "2026-04-14",
        },
    )
    assert draft_only.status_code == 201  # left as draft — must NOT count

    resp = client.get("/api/v1/analytics/monthly-sales-revenue")
    assert resp.status_code == 200
    april = next(d for d in resp.json()["data"] if d["month"] == "2026-04")
    assert april["revenue"] == float(invoice["total_amount"])  # not inflated by the draft


def test_top_selling_models_only_counts_finalized_invoices(client, party_id, item_code):
    _finalize_invoice(client, party_id, item_code, qty=3)  # finalized — counts

    draft_only = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": 99}],
            "transaction_date": "2026-04-14",
        },
    )
    assert draft_only.status_code == 201  # left as draft — must NOT count

    resp = client.get("/api/v1/analytics/top-selling-models")
    assert resp.status_code == 200
    row = next(d for d in resp.json()["data"] if d["item_name"].startswith("Platform"))
    assert row["quantity_sold"] == 3


def test_customer_debt_balance_includes_a_customer_with_positive_balance(client, party_id, item_code):
    _finalize_invoice(client, party_id, item_code, qty=1)
    resp = client.get("/api/v1/analytics/customer-debt-balance")
    assert resp.status_code == 200
    names = [d["party_name"] for d in resp.json()["data"]]
    assert "United Scale Ijtibah" in names


def test_low_stock_items_flags_items_at_or_below_threshold(client):
    client.post(
        "/api/v1/inventory/create",
        data={
            "item_code": "LOW-STOCK-1",
            "item_name": "Low Stock Widget",
            "unit": "pcs",
            "rate": "500",
            "quantity_in_stock": "2",
            "min_threshold": "5",
        },
    )
    resp = client.get("/api/v1/analytics/low-stock-items")
    assert resp.status_code == 200
    codes = [d["item_code"] for d in resp.json()["data"]]
    assert "LOW-STOCK-1" in codes


def test_payment_method_breakdown_groups_by_particular_name(client, party_id):
    payment = client.post(
        "/api/v1/invoices/payments",
        json={
            "party_id": party_id,
            "amount": 5000,
            "method": "Cheque",
            "transaction_date": "2026-04-15",
        },
    )
    assert payment.status_code == 201

    resp = client.get("/api/v1/analytics/payment-method-breakdown")
    assert resp.status_code == 200
    row = next(d for d in resp.json()["data"] if d["method"] == "Cheque")
    assert row["total"] == 5000.0


def test_category_wise_sales_groups_by_category_1(client, party_id):
    client.post(
        "/api/v1/inventory/create",
        data={
            "item_code": "CAT-TEST-1",
            "item_name": "Load Cell Widget",
            "unit": "pcs",
            "rate": "1000",
            "quantity_in_stock": "10",
            "category_1": "Load Cell",
        },
    )
    invoice = _finalize_invoice(client, party_id, "CAT-TEST-1", qty=2)

    resp = client.get("/api/v1/analytics/category-wise-sales")
    assert resp.status_code == 200
    row = next(d for d in resp.json()["data"] if d["category"] == "Load Cell")
    assert row["total"] == float(invoice["total_amount"])
