"""Section 16.2 — Stock Adjustment (physical count reconciliation)."""


def test_create_adjustment_updates_stock_and_computes_delta(client, item_code):
    resp = client.post(
        f"/api/v1/inventory/{item_code}/stock-adjustments",
        json={"counted_qty": 85, "reason": "count_correction", "note": "Recounted after monthly stock take"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["previous_qty"] == 100  # item_code fixture seeds 100 in stock
    assert body["counted_qty"] == 85
    assert body["delta"] == -15

    item = client.get(f"/api/v1/inventory/{item_code}").json()
    assert item["quantity_in_stock"] == 85


def test_adjustment_is_logged_to_activity_log(client, item_code):
    client.post(f"/api/v1/inventory/{item_code}/stock-adjustments", json={"counted_qty": 90, "reason": "damaged"})
    log = client.get("/api/v1/activity-log").json()
    assert len(log) == 1
    assert log[0]["action"] == "stock_adjustment"
    assert item_code in log[0]["target_description"]


def test_invalid_reason_rejected(client, item_code):
    resp = client.post(
        f"/api/v1/inventory/{item_code}/stock-adjustments", json={"counted_qty": 90, "reason": "made_up_reason"}
    )
    assert resp.status_code == 400


def test_unknown_item_returns_404(client):
    resp = client.post("/api/v1/inventory/NOPE/stock-adjustments", json={"counted_qty": 5, "reason": "other"})
    assert resp.status_code == 404


def test_list_adjustments_newest_first(client, item_code):
    client.post(f"/api/v1/inventory/{item_code}/stock-adjustments", json={"counted_qty": 90, "reason": "damaged"})
    client.post(f"/api/v1/inventory/{item_code}/stock-adjustments", json={"counted_qty": 80, "reason": "lost"})

    resp = client.get(f"/api/v1/inventory/{item_code}/stock-adjustments")
    body = resp.json()
    assert len(body) == 2
    assert body[0]["reason"] == "lost"  # newest first
    assert body[0]["previous_qty"] == 90  # chained off the first adjustment's result


def test_stock_adjustments_are_admin_only(raw_client, seeded_staff):
    from app.services import auth_service

    token = auth_service.create_access_token(seeded_staff["id"], seeded_staff["role"])
    raw_client.cookies.set("omega_session", token)
    # Admin-only RBAC is enforced before the item lookup even happens, so no
    # item needs to exist for this 403 check.
    resp = raw_client.post("/api/v1/inventory/SOME-ITEM/stock-adjustments", json={"counted_qty": 5, "reason": "other"})
    assert resp.status_code == 403
