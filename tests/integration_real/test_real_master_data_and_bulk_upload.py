"""Verifies two additions built for the frontend's Inventory List screen
(PRD Section 6, Screen 3) against the real Supabase project: the categories
master-data listing endpoint, and the bulk-upload dry_run preview mode.

Every item this suite creates is prefixed ZZTEST_ and is deleted by
`real_env`'s teardown (tests/integration_real/conftest.py), whether or not
the tests pass.
"""

import io

import pandas as pd


def _xlsx_bytes(rows: list[dict]) -> bytes:
    df = pd.DataFrame(rows)
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return buffer.read()


def test_categories_endpoint_returns_real_seeded_names(real_env):
    """db/schema.sql seeds categories_1 with: All, Indicator, Load Cell,
    Plat Form, Key Pad, Crane Scales, Top Loading Scale — 'All' is a literal
    row but must not appear in the response (Section 6 Screen 3's own
    'All Items' pseudo-tab covers that instead)."""
    client, _created = real_env
    resp = client.get("/api/v1/master-data/categories")
    assert resp.status_code == 200
    body = resp.json()
    assert "All" not in body["category_1"]
    for expected in ("Indicator", "Load Cell", "Plat Form", "Key Pad", "Crane Scales", "Top Loading Scale"):
        assert expected in body["category_1"], f"{expected!r} missing from real categories_1: {body['category_1']}"
    assert body["category_1"] == sorted(body["category_1"])


def test_units_endpoint_returns_real_seeded_names(real_env):
    """db/schema.sql seeds units with: pcs, box, carton, KG, Grms."""
    client, _created = real_env
    resp = client.get("/api/v1/master-data/units")
    assert resp.status_code == 200
    units = resp.json()["units"]
    for expected in ("pcs", "box", "carton", "KG", "Grms"):
        assert expected in units, f"{expected!r} missing from real units: {units}"
    assert units == sorted(units)


def test_bulk_upload_dry_run_writes_nothing_then_commit_does(real_env, run_id):
    client, created = real_env
    # item_code is normalized to uppercase server-side (InventoryItemBase.normalize_item_code)
    item_code = f"ZZTEST_BULK_{run_id}".upper()

    rows = [
        {
            "item_code": item_code,
            "item_name": "ZZTEST Bulk Item",
            "category_1": "",
            "category_2": "",
            "unit": "pcs",
            "rate": 42,
            "quantity_in_stock": 3,
            "min_threshold": 1,
        }
    ]
    file_bytes = _xlsx_bytes(rows)

    preview = client.post(
        "/api/v1/inventory/bulk-upload",
        data={"dry_run": "true"},
        files={"file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["committed"] is False
    assert preview_body["inserted"] == 1
    assert preview_body["preview_rows"][0]["item_code"] == item_code
    assert preview_body["preview_rows"][0]["status"] == "insert"

    # dry_run must not have written the row
    assert client.get(f"/api/v1/inventory/{item_code}").status_code == 404

    commit = client.post(
        "/api/v1/inventory/bulk-upload",
        files={"file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert commit.status_code == 200, commit.text
    commit_body = commit.json()
    assert commit_body["committed"] is True
    assert commit_body["inserted"] == 1
    created["item_codes"].append(item_code)

    fetched = client.get(f"/api/v1/inventory/{item_code}")
    assert fetched.status_code == 200
    assert fetched.json()["item_name"] == "ZZTEST Bulk Item"
