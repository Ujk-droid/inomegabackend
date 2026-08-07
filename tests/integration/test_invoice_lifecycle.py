def test_draft_create_uses_catalog_rate_by_default(client, party_id, item_code):
    resp = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": 2}],
            "transaction_date": "2026-07-30",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["invoice_state"] == "draft"
    assert body["invoice_no"] is None
    assert len(body["line_items"]) == 1
    assert body["line_items"][0]["rate"] == 12300
    assert body["line_items"][0]["line_total"] == 24600
    assert body["total_amount"] == 24600
    assert body["current_balance"] == 24600


def test_draft_create_applies_discount_once_at_header_level(client, party_id, item_code):
    resp = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": 1, "rate": 1000}],
            "discount_amount": 100,
            "transaction_date": "2026-07-30",
        },
    )
    body = resp.json()
    assert body["total_amount"] == 900


def test_draft_is_editable(client, party_id, item_code):
    created = client.post(
        "/api/v1/invoices/draft",
        json={"party_id": party_id, "line_items": [{"item_code": item_code, "qty": 1}], "transaction_date": "2026-07-30"},
    ).json()

    resp = client.put(f"/api/v1/invoices/{created['id']}", json={"line_items": [{"item_code": item_code, "qty": 3}]})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["line_items"]) == 1
    assert body["line_items"][0]["qty"] == 3
    assert body["total_amount"] == 36900


def test_finalize_assigns_invoice_no_and_due_date_and_decrements_stock(client, party_id, item_code):
    created = client.post(
        "/api/v1/invoices/draft",
        json={"party_id": party_id, "line_items": [{"item_code": item_code, "qty": 5}], "transaction_date": "2026-07-23"},
    ).json()

    resp = client.post(f"/api/v1/invoices/{created['id']}/finalize")
    assert resp.status_code == 200
    body = resp.json()
    assert body["invoice_state"] == "finalized"
    assert body["invoice_no"] == "1"  # first invoice in a fresh table (Section 5.3 empty-table edge case)
    assert body["due_date"] == "2026-08-07"  # transaction_date + 15 days
    assert body["can_dispatch"] is True  # below Human Gate threshold

    item = client.get(f"/api/v1/inventory/{item_code}").json()
    assert item["quantity_in_stock"] == 95  # started at 100, sale of 5 decrements it


def test_finalize_rejects_insufficient_stock(client, party_id, item_code):
    created = client.post(
        "/api/v1/invoices/draft",
        json={"party_id": party_id, "line_items": [{"item_code": item_code, "qty": 999}], "transaction_date": "2026-07-30"},
    ).json()

    resp = client.post(f"/api/v1/invoices/{created['id']}/finalize")
    assert resp.status_code == 400


def test_cannot_edit_finalized_invoice_directly(client, party_id, item_code):
    created = client.post(
        "/api/v1/invoices/draft",
        json={"party_id": party_id, "line_items": [{"item_code": item_code, "qty": 1}], "transaction_date": "2026-07-30"},
    ).json()
    client.post(f"/api/v1/invoices/{created['id']}/finalize")

    resp = client.put(f"/api/v1/invoices/{created['id']}", json={"line_items": [{"item_code": item_code, "qty": 5}]})
    assert resp.status_code == 409


def test_cannot_finalize_twice(client, party_id, item_code):
    created = client.post(
        "/api/v1/invoices/draft",
        json={"party_id": party_id, "line_items": [{"item_code": item_code, "qty": 1}], "transaction_date": "2026-07-30"},
    ).json()
    client.post(f"/api/v1/invoices/{created['id']}/finalize")

    resp = client.post(f"/api/v1/invoices/{created['id']}/finalize")
    assert resp.status_code == 409


def test_correction_cannot_target_a_draft(client, party_id, item_code):
    created = client.post(
        "/api/v1/invoices/draft",
        json={"party_id": party_id, "line_items": [{"item_code": item_code, "qty": 1}], "transaction_date": "2026-07-30"},
    ).json()

    resp = client.post(
        f"/api/v1/invoices/{created['id']}/correct",
        json={"reason": "typo", "line_items": [{"item_code": item_code, "qty": 2}]},
    )
    assert resp.status_code == 409


def test_correction_entry_preserves_original_and_updates_balance(client, party_id, item_code):
    created = client.post(
        "/api/v1/invoices/draft",
        json={"party_id": party_id, "line_items": [{"item_code": item_code, "qty": 15}], "transaction_date": "2026-07-23"},
    ).json()
    finalized = client.post(f"/api/v1/invoices/{created['id']}/finalize").json()
    assert finalized["total_amount"] == 184500  # matches INV-2127's total (Section 2.3)

    # correction reduces qty from 15 to 10 -> new total 123000, delta = -61500 (Credit Note)
    resp = client.post(
        f"/api/v1/invoices/{created['id']}/correct",
        json={"reason": "customer returned 5 units", "line_items": [{"item_code": item_code, "qty": 10}]},
    )
    assert resp.status_code == 201
    correction = resp.json()
    assert correction["correction_of"] == created["id"]
    assert correction["correction_reason"] == "customer returned 5 units"
    assert correction["current_balance"] == 184500 - 61500

    # Section 16.4 — Fix This Invoice is a sensitive Admin write, now audited.
    log = client.get("/api/v1/activity-log").json()
    assert any(entry["action"] == "invoice_corrected" for entry in log)

    # original untouched
    original = client.get(f"/api/v1/invoices/{created['id']}").json()
    assert len(original["line_items"]) == 1
    assert original["line_items"][0]["qty"] == 15
    assert original["total_amount"] == 184500
    assert original["current_balance"] == 184500


def test_record_payment_updates_balance_immediately(client, party_id, item_code):
    created = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": 1, "rate": 1000}],
            "transaction_date": "2026-07-30",
        },
    ).json()
    client.post(f"/api/v1/invoices/{created['id']}/finalize")

    resp = client.post(
        "/api/v1/invoices/payments",
        json={
            "party_id": party_id,
            "amount": 400,
            "method": "Cash",
            "payment_reference": None,
            "transaction_date": "2026-07-30",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["txn_type"] == "receiving"
    assert body["current_balance"] == 600
    assert body["approval_status"] == "approved"
    assert body["line_items"] == []  # a 'receiving' row has no line items


def test_backdated_payment_still_anchors_the_next_transactions_previous_balance(client, party_id, item_code):
    """A backdated Record Payment (an earlier transaction_date than an
    already-existing row) must still net into previous_balance for whatever
    gets inserted next — the anchor follows insertion order, not
    transaction_date, since a finalized row's stored current_balance is never
    recomputed after the fact (Section 5.1). If the anchor followed
    transaction_date instead, this backdated payment's -400 would silently
    stop counting toward the party's balance the moment a later transaction
    is inserted, even though the payment genuinely happened."""
    sale = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": 1, "rate": 1000}],
            "transaction_date": "2026-07-20",
        },
    ).json()
    client.post(f"/api/v1/invoices/{sale['id']}/finalize")

    payment = client.post(
        "/api/v1/invoices/payments",
        json={
            "party_id": party_id,
            "amount": 400,
            "method": "Cash",
            "transaction_date": "2026-07-10",  # backdated — earlier than the sale above
        },
    )
    assert payment.status_code == 201
    assert payment.json()["current_balance"] == 600  # 1000 - 400, inserted after the sale

    next_sale = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": 1, "rate": 500}],
            "transaction_date": "2026-07-25",
        },
    ).json()
    assert next_sale["previous_balance"] == 600  # anchored on the payment (last inserted), not the sale
    assert next_sale["current_balance"] == 1100


def test_party_ledger_lists_newest_first(client, party_id, item_code):
    first = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": 1, "rate": 100}],
            "transaction_date": "2026-07-01",
        },
    ).json()
    client.post(f"/api/v1/invoices/{first['id']}/finalize")

    second = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": 1, "rate": 200}],
            "transaction_date": "2026-07-15",
        },
    ).json()
    client.post(f"/api/v1/invoices/{second['id']}/finalize")

    resp = client.get(f"/api/v1/parties/{party_id}/ledger")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2
    assert rows[0]["id"] == second["id"]  # newest first, Section 5.2
    assert rows[1]["id"] == first["id"]


def test_multi_item_invoice_totals_correctly(client, party_id, item_code):
    """New test (per the PRD fix): a real invoice can now hold more than one
    product, matching the business's actual Sale form (an 'Add To List' table)."""
    second_item = client.post(
        "/api/v1/inventory/create",
        data={"item_code": "LC-500KG", "item_name": "Load Cell 500Kg", "unit": "pcs", "rate": "4500", "quantity_in_stock": "50"},
    ).json()["item_code"]

    created = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [
                {"item_code": item_code, "qty": 2, "rate": 12300},   # line_total 24600
                {"item_code": second_item, "qty": 3, "rate": 4500},  # line_total 13500
            ],
            "discount_amount": 100,
            "transaction_date": "2026-07-30",
        },
    )
    assert created.status_code == 201
    body = created.json()

    assert len(body["line_items"]) == 2
    assert body["line_items"][0]["line_number"] == 1
    assert body["line_items"][0]["item_code"] == item_code
    assert body["line_items"][0]["line_total"] == 24600
    assert body["line_items"][1]["line_number"] == 2
    assert body["line_items"][1]["item_code"] == second_item
    assert body["line_items"][1]["line_total"] == 13500

    # total_amount == SUM(line_totals) - discount_amount == (24600 + 13500) - 100
    assert body["total_amount"] == 38000
    assert body["current_balance"] == 38000

    finalized = client.post(f"/api/v1/invoices/{body['id']}/finalize").json()
    assert finalized["total_amount"] == 38000

    first_item_after = client.get(f"/api/v1/inventory/{item_code}").json()
    second_item_after = client.get(f"/api/v1/inventory/{second_item}").json()
    assert first_item_after["quantity_in_stock"] == 98   # 100 - 2
    assert second_item_after["quantity_in_stock"] == 47  # 50 - 3


def test_list_invoices_is_newest_first_and_excludes_payments(client, party_id, item_code):
    first = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": 1, "rate": 100}],
            "transaction_date": "2026-07-01",
        },
    ).json()
    client.post(f"/api/v1/invoices/{first['id']}/finalize")

    second = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": 1, "rate": 200}],
            "transaction_date": "2026-07-15",
        },
    ).json()
    client.post(f"/api/v1/invoices/{second['id']}/finalize")

    # A payment ('receiving') row must never show up in the Invoices list (Screen 6) —
    # it's a distinct list from the Sale rows above, same distinction Section 5.4.D draws.
    client.post(
        "/api/v1/invoices/payments",
        json={"party_id": party_id, "amount": 50, "method": "Cash", "transaction_date": "2026-07-20"},
    )

    resp = client.get("/api/v1/invoices")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2
    assert rows[0]["id"] == second["id"]  # newest first
    assert rows[1]["id"] == first["id"]
    assert all(r["txn_type"] == "sale" for r in rows)
