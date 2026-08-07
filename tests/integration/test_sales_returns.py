"""Section 16.3 — Sales Return."""


def _finalized_invoice(client, party_id, item_code, qty=10, rate=1000):
    draft = client.post(
        "/api/v1/invoices/draft",
        json={"party_id": party_id, "line_items": [{"item_code": item_code, "qty": qty, "rate": rate}], "transaction_date": "2026-07-30"},
    ).json()
    return client.post(f"/api/v1/invoices/{draft['id']}/finalize").json()


def test_return_restores_stock_and_credits_balance(client, party_id, item_code):
    before_item = client.get(f"/api/v1/inventory/{item_code}").json()
    invoice = _finalized_invoice(client, party_id, item_code, qty=10, rate=1000)
    after_sale_item = client.get(f"/api/v1/inventory/{item_code}").json()
    assert after_sale_item["quantity_in_stock"] == before_item["quantity_in_stock"] - 10

    resp = client.post(
        f"/api/v1/invoices/{invoice['id']}/returns",
        json={"item_code": item_code, "qty_returned": 3, "reason": "Wrong size delivered"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["qty_returned"] == 3
    assert body["original_invoice_id"] == invoice["id"]

    after_return_item = client.get(f"/api/v1/inventory/{item_code}").json()
    assert after_return_item["quantity_in_stock"] == before_item["quantity_in_stock"] - 7  # 10 sold, 3 returned

    # party's balance is credited: 10000 owed, minus 3*1000 = 3000 credited back
    ledger = client.get(f"/api/v1/parties/{party_id}/ledger").json()
    assert ledger[0]["current_balance"] == 7000
    assert ledger[0]["txn_type"] == "receiving"


def test_return_is_logged_to_activity_log(client, party_id, item_code):
    invoice = _finalized_invoice(client, party_id, item_code, qty=5, rate=500)
    client.post(f"/api/v1/invoices/{invoice['id']}/returns", json={"item_code": item_code, "qty_returned": 2})

    log = client.get("/api/v1/activity-log").json()
    assert len(log) == 1
    assert log[0]["action"] == "sales_return"


def test_cannot_return_more_than_was_sold(client, party_id, item_code):
    invoice = _finalized_invoice(client, party_id, item_code, qty=5, rate=500)
    resp = client.post(f"/api/v1/invoices/{invoice['id']}/returns", json={"item_code": item_code, "qty_returned": 6})
    assert resp.status_code == 400


def test_cannot_return_more_than_remains_after_a_prior_partial_return(client, party_id, item_code):
    """10 sold, 6 already returned in an earlier call — only 4 remain
    returnable. A second return of 8 must be rejected against the remainder,
    not re-validated against the original qty=10 (which would let 6+8=14 be
    returned/credited against only 10 ever sold)."""
    before_item = client.get(f"/api/v1/inventory/{item_code}").json()
    invoice = _finalized_invoice(client, party_id, item_code, qty=10, rate=1000)

    first = client.post(f"/api/v1/invoices/{invoice['id']}/returns", json={"item_code": item_code, "qty_returned": 6})
    assert first.status_code == 201

    second = client.post(f"/api/v1/invoices/{invoice['id']}/returns", json={"item_code": item_code, "qty_returned": 8})
    assert second.status_code == 400

    # exactly the remaining 4 is still allowed
    third = client.post(f"/api/v1/invoices/{invoice['id']}/returns", json={"item_code": item_code, "qty_returned": 4})
    assert third.status_code == 201

    # net effect: -10 sold, +6 returned, +4 returned == back to the pre-sale
    # stock level — never inflated by the rejected 8
    after_item = client.get(f"/api/v1/inventory/{item_code}").json()
    assert after_item["quantity_in_stock"] == before_item["quantity_in_stock"]


def test_cannot_return_item_not_on_the_invoice(client, party_id, item_code):
    other_item = client.post(
        "/api/v1/inventory/create", data={"item_code": "OTHER-ITEM", "item_name": "Other", "unit": "pcs", "rate": "10", "quantity_in_stock": "50"}
    ).json()["item_code"]
    invoice = _finalized_invoice(client, party_id, item_code, qty=5, rate=500)
    resp = client.post(f"/api/v1/invoices/{invoice['id']}/returns", json={"item_code": other_item, "qty_returned": 1})
    assert resp.status_code == 400


def test_cannot_return_against_a_draft_invoice(client, party_id, item_code):
    draft = client.post(
        "/api/v1/invoices/draft",
        json={"party_id": party_id, "line_items": [{"item_code": item_code, "qty": 5, "rate": 500}], "transaction_date": "2026-07-30"},
    ).json()
    resp = client.post(f"/api/v1/invoices/{draft['id']}/returns", json={"item_code": item_code, "qty_returned": 1})
    assert resp.status_code == 409


def test_list_returns_for_invoice(client, party_id, item_code):
    invoice = _finalized_invoice(client, party_id, item_code, qty=10, rate=1000)
    client.post(f"/api/v1/invoices/{invoice['id']}/returns", json={"item_code": item_code, "qty_returned": 2})
    client.post(f"/api/v1/invoices/{invoice['id']}/returns", json={"item_code": item_code, "qty_returned": 1})

    resp = client.get(f"/api/v1/invoices/{invoice['id']}/returns")
    body = resp.json()
    assert len(body) == 2
