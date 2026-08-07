from app.services import auth_service


def test_get_negotiated_rate_is_null_when_none_set(client, party_id, item_code):
    resp = client.get(f"/api/v1/parties/{party_id}/negotiated-rates/{item_code}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["negotiated_rate"] is None
    assert body["party_id"] == party_id
    assert body["item_code"] == item_code


def test_admin_can_set_negotiated_rate(client, party_id, item_code):
    resp = client.post(
        f"/api/v1/parties/{party_id}/negotiated-rates",
        json={"item_code": item_code, "negotiated_rate": 11000},
    )
    assert resp.status_code == 201
    assert resp.json()["negotiated_rate"] == 11000

    fetched = client.get(f"/api/v1/parties/{party_id}/negotiated-rates/{item_code}")
    assert fetched.json()["negotiated_rate"] == 11000


def test_setting_negotiated_rate_again_updates_not_duplicates(client, party_id, item_code, fake_supabase):
    client.post(f"/api/v1/parties/{party_id}/negotiated-rates", json={"item_code": item_code, "negotiated_rate": 11000})
    client.post(f"/api/v1/parties/{party_id}/negotiated-rates", json={"item_code": item_code, "negotiated_rate": 10500})

    fetched = client.get(f"/api/v1/parties/{party_id}/negotiated-rates/{item_code}")
    assert fetched.json()["negotiated_rate"] == 10500
    assert len(fake_supabase.tables["party_item_rates"]) == 1


def test_set_negotiated_rate_unknown_party_404s(client, item_code):
    resp = client.post(
        "/api/v1/parties/00000000-0000-0000-0000-000000000000/negotiated-rates",
        json={"item_code": item_code, "negotiated_rate": 5000},
    )
    assert resp.status_code == 404


def test_set_negotiated_rate_unknown_item_404s(client, party_id):
    resp = client.post(
        f"/api/v1/parties/{party_id}/negotiated-rates",
        json={"item_code": "NOT-A-REAL-CODE", "negotiated_rate": 5000},
    )
    assert resp.status_code == 404


def test_set_negotiated_rate_requires_admin(raw_client, seeded_staff, fake_supabase):
    # Seeded directly into fake_supabase (not via the `client`/party_id/item_code
    # fixtures) — those set app.dependency_overrides[get_current_user] to the
    # fake Admin for the rest of the test's lifetime, which would silently
    # mask this exact 403 check since overrides win over raw_client's real
    # cookie-decoded auth.
    fake_supabase.tables["parties"].append(
        {"id": "party-1", "party_name": "ZZTEST Party", "party_type": "customer"}
    )
    fake_supabase.tables["inventory_items"].append(
        {"id": "item-1", "item_code": "ZZ-ITEM", "item_name": "Test Item", "rate": 100}
    )

    token = auth_service.create_access_token(seeded_staff["id"], seeded_staff["role"])
    raw_client.cookies.set("omega_session", token)

    resp = raw_client.post(
        "/api/v1/parties/party-1/negotiated-rates",
        json={"item_code": "ZZ-ITEM", "negotiated_rate": 5000},
    )
    assert resp.status_code == 403
