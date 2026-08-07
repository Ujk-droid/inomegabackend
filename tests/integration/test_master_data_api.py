def test_list_categories_returns_seeded_names(client):
    resp = client.get("/api/v1/master-data/categories")
    assert resp.status_code == 200
    body = resp.json()
    assert body["category_1"] == ["Load Cell", "Platform Scales"]
    assert body["category_2"] == ["Digital"]


def test_list_categories_excludes_literal_all_row(fake_supabase, client):
    fake_supabase.seed("categories_1", "All")
    resp = client.get("/api/v1/master-data/categories")
    assert resp.status_code == 200
    assert "All" not in resp.json()["category_1"]


def test_list_units_returns_seeded_names(client):
    resp = client.get("/api/v1/master-data/units")
    assert resp.status_code == 200
    assert resp.json()["units"] == ["box", "pcs"]


def test_list_particulars_returns_seeded_names(client):
    resp = client.get("/api/v1/master-data/particulars")
    assert resp.status_code == 200
    assert resp.json()["particulars"] == ["Bank Transfer", "Cash", "Cheque", "Discount", "Online"]


def test_list_bank_accounts_returns_only_active(fake_supabase, client):
    fake_supabase.seed("bank_accounts", "Closed Account", name_field="bank_name", is_active=False)
    resp = client.get("/api/v1/master-data/bank-accounts")
    assert resp.status_code == 200
    assert resp.json()["bank_accounts"] == ["Cash Received", "Meezan Bank"]
