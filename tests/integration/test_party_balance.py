"""Section 5.4.I's Party Detail stat tiles — GET /parties/{id}/balance now
also returns lifetime_business (sum of all sale/purchase amounts)."""


def test_balance_defaults_to_zero_for_a_new_party(client, party_id):
    resp = client.get(f"/api/v1/parties/{party_id}/balance")
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_balance"] == 0.0
    assert body["lifetime_business"] == 0.0


def test_lifetime_business_sums_sale_invoices(client, party_id, item_code):
    client.post(
        "/api/v1/invoices/draft",
        json={"party_id": party_id, "line_items": [{"item_code": item_code, "qty": 2, "rate": 5000}], "transaction_date": "2026-07-01"},
    ).json()
    draft2 = client.post(
        "/api/v1/invoices/draft",
        json={"party_id": party_id, "line_items": [{"item_code": item_code, "qty": 1, "rate": 3000}], "transaction_date": "2026-07-02"},
    ).json()
    client.post(f"/api/v1/invoices/{draft2['id']}/finalize")

    resp = client.get(f"/api/v1/parties/{party_id}/balance")
    # Only the finalized draft actually posts to the ledger as a real row —
    # the other draft was never finalized, so it shouldn't count.
    assert resp.json()["lifetime_business"] == 3000


def test_lifetime_business_includes_purchases(client, supplier_id, item_code):
    client.post(
        "/api/v1/purchases",
        json={"party_id": supplier_id, "line_items": [{"item_code": item_code, "qty": 4, "rate": 1000}], "transaction_date": "2026-07-01"},
    )
    resp = client.get(f"/api/v1/parties/{supplier_id}/balance")
    assert resp.json()["lifetime_business"] == 4000


def test_lifetime_business_combines_sales_and_purchases_for_a_both_party(client, item_code):
    both = client.post("/api/v1/parties", json={"party_name": "Both Party", "party_type": "both"}).json()

    draft = client.post(
        "/api/v1/invoices/draft",
        json={"party_id": both["id"], "line_items": [{"item_code": item_code, "qty": 1, "rate": 10000}], "transaction_date": "2026-07-01"},
    ).json()
    client.post(f"/api/v1/invoices/{draft['id']}/finalize")
    client.post(
        "/api/v1/purchases",
        json={"party_id": both["id"], "line_items": [{"item_code": item_code, "qty": 1, "rate": 2500}], "transaction_date": "2026-07-02"},
    )

    resp = client.get(f"/api/v1/parties/{both['id']}/balance")
    assert resp.json()["lifetime_business"] == 12500
