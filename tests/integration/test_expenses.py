def test_expense_without_party_is_valid(client):
    # Section 12.1: "An Expense entry with no linked party (e.g. a utility bill)
    # is still valid and appears in the Expenses list correctly"
    resp = client.post(
        "/api/v1/expenses",
        json={"expense_date": "2026-07-30", "description": "Electricity bill", "amount": 4500, "particular": "Cash"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["party_id"] is None
    assert body["amount"] == 4500
    assert body["serial_number"] == 1
    assert body["particular_name"] == "Cash"


def test_expense_list_resolves_particular_name(client):
    client.post(
        "/api/v1/expenses",
        json={"expense_date": "2026-07-30", "description": "Fuel", "amount": 1200, "particular": "Cash"},
    )
    resp = client.get("/api/v1/expenses")
    body = resp.json()
    assert body[0]["particular_name"] == "Cash"


def test_expense_with_party(client, party_id):
    resp = client.post(
        "/api/v1/expenses",
        json={"expense_date": "2026-07-30", "party_id": party_id, "description": "Rider payment", "amount": 500},
    )
    assert resp.status_code == 201
    assert resp.json()["party_id"] == party_id


def test_expense_list_filters_by_date_range(client):
    client.post("/api/v1/expenses", json={"expense_date": "2026-07-01", "description": "old", "amount": 100})
    client.post("/api/v1/expenses", json={"expense_date": "2026-07-30", "description": "new", "amount": 200})

    resp = client.get("/api/v1/expenses", params={"start_date": "2026-07-15"})
    body = resp.json()
    assert len(body) == 1
    assert body[0]["description"] == "new"
