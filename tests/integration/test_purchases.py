def test_purchase_increases_stock(client, supplier_id, item_code):
    before = client.get(f"/api/v1/inventory/{item_code}").json()
    assert before["quantity_in_stock"] == 100

    resp = client.post(
        "/api/v1/purchases",
        json={
            "party_id": supplier_id,
            "line_items": [{"item_code": item_code, "qty": 20, "rate": 9000}],
            "transaction_date": "2026-07-30",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["purchase_bill_no"] == "1"
    assert len(body["line_items"]) == 1
    assert body["total_amount"] == 180000
    assert body["current_balance"] == 180000

    after = client.get(f"/api/v1/inventory/{item_code}").json()
    assert after["quantity_in_stock"] == 120  # the reverse of a Sale's decrease (Section 5.4.B)


def test_purchase_balance_chain_accumulates_per_supplier(client, supplier_id, item_code):
    first = client.post(
        "/api/v1/purchases",
        json={
            "party_id": supplier_id,
            "line_items": [{"item_code": item_code, "qty": 5, "rate": 1000}],
            "transaction_date": "2026-07-01",
        },
    ).json()
    assert first["current_balance"] == 5000

    second = client.post(
        "/api/v1/purchases",
        json={
            "party_id": supplier_id,
            "line_items": [{"item_code": item_code, "qty": 3, "rate": 1000}],
            "transaction_date": "2026-07-15",
        },
    ).json()
    assert second["previous_balance"] == 5000
    assert second["current_balance"] == 8000
    assert second["purchase_bill_no"] == "2"


def test_list_purchases_without_party_id_returns_all(client, supplier_id, item_code):
    other_supplier = client.post(
        "/api/v1/parties", json={"party_name": "Other Supplier", "party_type": "supplier"}
    ).json()["id"]

    client.post(
        "/api/v1/purchases",
        json={"party_id": supplier_id, "line_items": [{"item_code": item_code, "qty": 1, "rate": 100}], "transaction_date": "2026-07-01"},
    )
    client.post(
        "/api/v1/purchases",
        json={"party_id": other_supplier, "line_items": [{"item_code": item_code, "qty": 1, "rate": 100}], "transaction_date": "2026-07-02"},
    )

    resp = client.get("/api/v1/purchases")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert {row["party_id"] for row in body} == {supplier_id, other_supplier}


def test_list_purchases_with_party_id_filters_to_that_supplier(client, supplier_id, item_code):
    other_supplier = client.post(
        "/api/v1/parties", json={"party_name": "Yet Another Supplier", "party_type": "supplier"}
    ).json()["id"]

    client.post(
        "/api/v1/purchases",
        json={"party_id": supplier_id, "line_items": [{"item_code": item_code, "qty": 1, "rate": 100}], "transaction_date": "2026-07-01"},
    )
    client.post(
        "/api/v1/purchases",
        json={"party_id": other_supplier, "line_items": [{"item_code": item_code, "qty": 1, "rate": 100}], "transaction_date": "2026-07-02"},
    )

    resp = client.get("/api/v1/purchases", params={"party_id": supplier_id})
    body = resp.json()
    assert len(body) == 1
    assert body[0]["party_id"] == supplier_id


def test_purchase_for_unknown_party_returns_404(client, item_code):
    resp = client.post(
        "/api/v1/purchases",
        json={
            "party_id": "00000000-0000-0000-0000-000000000000",
            "line_items": [{"item_code": item_code, "qty": 1, "rate": 100}],
            "transaction_date": "2026-07-30",
        },
    )
    assert resp.status_code == 404


def test_multi_item_purchase_increases_stock_for_every_line(client, supplier_id, item_code):
    second_item = client.post(
        "/api/v1/inventory/create",
        data={"item_code": "LC-500KG", "item_name": "Load Cell 500Kg", "unit": "pcs", "rate": "4500", "quantity_in_stock": "50"},
    ).json()["item_code"]

    resp = client.post(
        "/api/v1/purchases",
        json={
            "party_id": supplier_id,
            "line_items": [
                {"item_code": item_code, "qty": 10, "rate": 9000},
                {"item_code": second_item, "qty": 4, "rate": 4000},
            ],
            "discount_amount": 200,
            "transaction_date": "2026-07-30",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["total_amount"] == 90000 + 16000 - 200

    first_after = client.get(f"/api/v1/inventory/{item_code}").json()
    second_after = client.get(f"/api/v1/inventory/{second_item}").json()
    assert first_after["quantity_in_stock"] == 110  # 100 + 10
    assert second_after["quantity_in_stock"] == 54   # 50 + 4
