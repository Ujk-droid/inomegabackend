import io
import zipfile

import pandas as pd


def test_create_item_success(client):
    resp = client.post(
        "/api/v1/inventory/create",
        data={"item_code": "p-16-s-a-mk", "item_name": "Platform Scale", "unit": "pcs", "rate": "12300"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["item_code"] == "P-16-S-A-MK"
    assert body["rate"] == 12300
    assert body["is_low_stock"] is True  # quantity_in_stock defaults to 0 <= min_threshold 5


def test_create_duplicate_item_code_returns_inline_error(client):
    payload = {"item_code": "DUP-1", "item_name": "Item", "unit": "pcs", "rate": "100"}
    first = client.post("/api/v1/inventory/create", data=payload)
    assert first.status_code == 201

    second = client.post("/api/v1/inventory/create", data=payload)
    assert second.status_code == 409
    assert second.json()["detail"] == "This item code already exists"


def test_create_with_unknown_unit_returns_400(client):
    resp = client.post(
        "/api/v1/inventory/create",
        data={"item_code": "X-1", "item_name": "Item", "unit": "nonexistent-unit", "rate": "100"},
    )
    assert resp.status_code == 400


def test_create_with_category_resolves_names(client):
    resp = client.post(
        "/api/v1/inventory/create",
        data={
            "item_code": "X-2",
            "item_name": "Item",
            "unit": "pcs",
            "rate": "100",
            "category_1": "Load Cell",
            "category_2": "Digital",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["category_1"] == "Load Cell"
    assert body["category_2"] == "Digital"


def test_new_item_appears_at_top_of_list(client):
    client.post("/api/v1/inventory/create", data={"item_code": "OLD-1", "item_name": "Old", "unit": "pcs", "rate": "10"})
    client.post("/api/v1/inventory/create", data={"item_code": "NEW-1", "item_name": "New", "unit": "pcs", "rate": "10"})

    resp = client.get("/api/v1/inventory")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["items"][0]["item_code"] == "NEW-1"


def test_get_single_item(client):
    client.post("/api/v1/inventory/create", data={"item_code": "GET-1", "item_name": "Item", "unit": "pcs", "rate": "50"})
    resp = client.get("/api/v1/inventory/GET-1")
    assert resp.status_code == 200
    assert resp.json()["item_name"] == "Item"


def test_get_missing_item_returns_404(client):
    resp = client.get("/api/v1/inventory/NOPE")
    assert resp.status_code == 404


def test_update_rate_and_stock(client):
    client.post("/api/v1/inventory/create", data={"item_code": "UPD-1", "item_name": "Item", "unit": "pcs", "rate": "50"})
    resp = client.put("/api/v1/inventory/UPD-1", data={"rate": "75", "quantity_in_stock": "20"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["rate"] == 75
    assert body["quantity_in_stock"] == 20
    assert body["is_low_stock"] is False  # 20 > default min_threshold 5


def test_update_missing_item_returns_404(client):
    resp = client.put("/api/v1/inventory/NOPE", data={"rate": "10"})
    assert resp.status_code == 404


def test_delete_item_then_get_returns_404(client):
    client.post("/api/v1/inventory/create", data={"item_code": "DEL-1", "item_name": "Item", "unit": "pcs", "rate": "10"})
    resp = client.delete("/api/v1/inventory/DEL-1")
    assert resp.status_code == 204

    resp = client.get("/api/v1/inventory/DEL-1")
    assert resp.status_code == 404


def test_delete_missing_item_returns_404(client):
    resp = client.delete("/api/v1/inventory/NOPE")
    assert resp.status_code == 404


def test_search_filters_by_name_or_code(client):
    client.post("/api/v1/inventory/create", data={"item_code": "SRC-1", "item_name": "Load Cell Sensor", "unit": "pcs", "rate": "10"})
    client.post("/api/v1/inventory/create", data={"item_code": "SRC-2", "item_name": "Indicator Head", "unit": "pcs", "rate": "10"})

    resp = client.get("/api/v1/inventory", params={"search": "load cell"})
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["item_code"] == "SRC-1"


def _xlsx_bytes(rows: list[dict]) -> bytes:
    df = pd.DataFrame(rows)
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return buffer.read()


def test_bulk_upload_inserts_updates_and_skips(client):
    # pre-existing item that the upload will update
    client.post("/api/v1/inventory/create", data={"item_code": "BULK-1", "item_name": "Old Name", "unit": "pcs", "rate": "10"})

    rows = [
        {"item_code": "BULK-1", "item_name": "Updated Name", "category_1": "", "category_2": "", "unit": "pcs", "rate": 15, "quantity_in_stock": 10, "min_threshold": 2},
        {"item_code": "BULK-2", "item_name": "New Item", "category_1": "", "category_2": "", "unit": "pcs", "rate": 20, "quantity_in_stock": 5, "min_threshold": 2},
        {"item_code": "BULK-3", "item_name": "Bad Rate", "category_1": "", "category_2": "", "unit": "pcs", "rate": "not-a-number", "quantity_in_stock": 5, "min_threshold": 2},
    ]
    file_bytes = _xlsx_bytes(rows)

    resp = client.post(
        "/api/v1/inventory/bulk-upload",
        files={"file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["total_rows"] == 3
    assert result["inserted"] == 1
    assert result["updated"] == 1
    assert result["skipped"] == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0]["item_code"] == "BULK-3"

    updated = client.get("/api/v1/inventory/BULK-1").json()
    assert updated["item_name"] == "Updated Name"
    assert updated["rate"] == 15


def test_bulk_upload_rejects_non_spreadsheet_file(client):
    resp = client.post(
        "/api/v1/inventory/bulk-upload",
        files={"file": ("test.txt", b"not a spreadsheet", "text/plain")},
    )
    assert resp.status_code == 400


def test_bulk_upload_dry_run_previews_without_committing(client):
    """Section 6 Screen 3 Step 2 — the preview call must report the same
    insert/update/error counts the real commit would, but write nothing."""
    client.post("/api/v1/inventory/create", data={"item_code": "DRY-1", "item_name": "Old Name", "unit": "pcs", "rate": "10"})

    rows = [
        {"item_code": "DRY-1", "item_name": "Updated Name", "category_1": "", "category_2": "", "unit": "pcs", "rate": 15, "quantity_in_stock": 10, "min_threshold": 2},
        {"item_code": "DRY-2", "item_name": "New Item", "category_1": "", "category_2": "", "unit": "pcs", "rate": 20, "quantity_in_stock": 5, "min_threshold": 2},
        {"item_code": "DRY-3", "item_name": "Bad Rate", "category_1": "", "category_2": "", "unit": "pcs", "rate": "not-a-number", "quantity_in_stock": 5, "min_threshold": 2},
    ]
    file_bytes = _xlsx_bytes(rows)

    resp = client.post(
        "/api/v1/inventory/bulk-upload",
        data={"dry_run": "true"},
        files={"file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["committed"] is False
    assert result["total_rows"] == 3
    assert result["inserted"] == 1
    assert result["updated"] == 1
    assert result["skipped"] == 1
    assert len(result["preview_rows"]) == 3
    statuses = {row["item_code"]: row["status"] for row in result["preview_rows"]}
    assert statuses["DRY-1"] == "update"
    assert statuses["DRY-2"] == "insert"
    assert statuses["DRY-3"] == "error"

    # nothing was actually written: DRY-1 unchanged, DRY-2 was never created
    unchanged = client.get("/api/v1/inventory/DRY-1").json()
    assert unchanged["item_name"] == "Old Name"
    assert unchanged["rate"] == 10
    assert client.get("/api/v1/inventory/DRY-2").status_code == 404


def test_bulk_upload_commit_after_dry_run_matches_preview(client):
    rows = [{"item_code": "DRY-CONFIRM", "item_name": "New Item", "category_1": "", "category_2": "", "unit": "pcs", "rate": 20, "quantity_in_stock": 5, "min_threshold": 2}]
    file_bytes = _xlsx_bytes(rows)

    preview = client.post(
        "/api/v1/inventory/bulk-upload",
        data={"dry_run": "true"},
        files={"file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    ).json()
    assert preview["inserted"] == 1
    assert client.get("/api/v1/inventory/DRY-CONFIRM").status_code == 404

    commit = client.post(
        "/api/v1/inventory/bulk-upload",
        files={"file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    ).json()
    assert commit["committed"] is True
    assert commit["inserted"] == 1
    assert client.get("/api/v1/inventory/DRY-CONFIRM").status_code == 200


def test_download_template_has_expected_columns(client):
    resp = client.get("/api/v1/inventory/bulk-upload/template")
    assert resp.status_code == 200
    df = pd.read_excel(io.BytesIO(resp.content), engine="openpyxl")
    assert list(df.columns) == [
        "item_code",
        "item_name",
        "category_1",
        "category_2",
        "unit",
        "rate",
        "quantity_in_stock",
        "min_threshold",
    ]


def _zip_bytes(images: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for filename, content in images.items():
            zf.writestr(filename, content)
    buffer.seek(0)
    return buffer.read()


def test_bulk_upload_with_images_zip_matches_by_item_code(client):
    """Section 10.2b — filename (minus extension) == item_code."""
    rows = [
        {"item_code": "IMG-1", "item_name": "Has Image", "category_1": "", "category_2": "", "unit": "pcs", "rate": 10, "quantity_in_stock": 5, "min_threshold": 2},
        {"item_code": "IMG-2", "item_name": "No Image", "category_1": "", "category_2": "", "unit": "pcs", "rate": 10, "quantity_in_stock": 5, "min_threshold": 2},
    ]
    file_bytes = _xlsx_bytes(rows)
    images_zip = _zip_bytes({"IMG-1.jpg": b"fake-jpeg-bytes"})

    resp = client.post(
        "/api/v1/inventory/bulk-upload",
        files={
            "file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            "images_zip": ("images.zip", images_zip, "application/zip"),
        },
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["inserted"] == 2
    assert result["images_matched"] == 1
    assert result["images_unmatched"] == 1

    with_image = client.get("/api/v1/inventory/IMG-1").json()
    assert with_image["cloudinary_image_url"] == "https://cdn.example.com/IMG-1.jpg"

    without_image = client.get("/api/v1/inventory/IMG-2").json()
    assert without_image["cloudinary_image_url"] is None


def test_bulk_upload_matches_images_nested_inside_a_folder(client):
    """Real bug: selecting a whole folder and choosing 'Compress to ZIP'
    (the ordinary way to zip a batch of product photos) nests every entry
    under a folder name — 'product-images/ITEM-1.jpg', not 'ITEM-1.jpg' at
    the zip root. Matching must depend only on the filename, not on it
    being at the archive's top level."""
    rows = [{"item_code": "NESTED-1", "item_name": "Nested Folder Item", "category_1": "", "category_2": "", "unit": "pcs", "rate": 10, "quantity_in_stock": 5, "min_threshold": 2}]
    file_bytes = _xlsx_bytes(rows)
    images_zip = _zip_bytes({"product-images/NESTED-1.jpg": b"fake-jpeg-bytes"})

    resp = client.post(
        "/api/v1/inventory/bulk-upload",
        files={
            "file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            "images_zip": ("images.zip", images_zip, "application/zip"),
        },
    )
    result = resp.json()
    assert result["images_matched"] == 1
    assert result["images_unmatched"] == 0
    assert result["image_filenames_found"] == ["product-images/NESTED-1.jpg"]

    item = client.get("/api/v1/inventory/NESTED-1").json()
    assert item["cloudinary_image_url"] == "https://cdn.example.com/NESTED-1.jpg"


def test_bulk_upload_matches_images_with_backslash_separators(client):
    """Real bug: some zip tools (older WinZip builds, some Windows
    Compress-Archive configurations) write '\\' as the path separator
    inside the archive instead of the ZIP-spec-mandated '/'. Matching must
    normalize either separator, not just '/'."""
    rows = [{"item_code": "BACKSLASH-1", "item_name": "Backslash Zip Item", "category_1": "", "category_2": "", "unit": "pcs", "rate": 10, "quantity_in_stock": 5, "min_threshold": 2}]
    file_bytes = _xlsx_bytes(rows)
    images_zip = _zip_bytes({"product-images\\BACKSLASH-1.jpg": b"fake-jpeg-bytes"})

    resp = client.post(
        "/api/v1/inventory/bulk-upload",
        files={
            "file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            "images_zip": ("images.zip", images_zip, "application/zip"),
        },
    )
    result = resp.json()
    assert result["images_matched"] == 1
    assert result["images_unmatched"] == 0

    item = client.get("/api/v1/inventory/BACKSLASH-1").json()
    assert item["cloudinary_image_url"] == "https://cdn.example.com/BACKSLASH-1.jpg"


def test_bulk_upload_result_reports_filenames_found_for_debugging(client):
    """Section 10.2b's own 'never silent' convention, extended: when
    nothing matches, the response itself must carry enough to debug it —
    what filenames the zip reader actually saw — without needing server log
    access."""
    rows = [{"item_code": "WONT-MATCH", "item_name": "No Match Item", "category_1": "", "category_2": "", "unit": "pcs", "rate": 10, "quantity_in_stock": 5, "min_threshold": 2}]
    file_bytes = _xlsx_bytes(rows)
    images_zip = _zip_bytes({"totally-different-name.jpg": b"fake-jpeg-bytes"})

    resp = client.post(
        "/api/v1/inventory/bulk-upload",
        files={
            "file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            "images_zip": ("images.zip", images_zip, "application/zip"),
        },
    )
    result = resp.json()
    assert result["images_matched"] == 0
    assert result["images_unmatched"] == 1
    assert result["image_filenames_found"] == ["totally-different-name.jpg"]


def test_bulk_upload_dry_run_never_matches_images(client):
    """Preview stays a pure, side-effect-free read — no Cloudinary calls."""
    rows = [{"item_code": "IMG-DRY", "item_name": "Dry Run Item", "category_1": "", "category_2": "", "unit": "pcs", "rate": 10, "quantity_in_stock": 5, "min_threshold": 2}]
    file_bytes = _xlsx_bytes(rows)
    images_zip = _zip_bytes({"IMG-DRY.png": b"fake-png-bytes"})

    resp = client.post(
        "/api/v1/inventory/bulk-upload",
        data={"dry_run": "true"},
        files={
            "file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            "images_zip": ("images.zip", images_zip, "application/zip"),
        },
    )
    result = resp.json()
    assert result["images_matched"] == 0
    assert result["images_unmatched"] == 0


def test_bulk_upload_image_upload_failure_does_not_fail_the_row(client, monkeypatch):
    """A real bug caught during live verification: Cloudinary rejecting one
    bad image file (or any upload failure) must never turn an
    already-successful create_item/update_item into a reported row error —
    the item itself was genuinely imported; only its thumbnail is missing."""

    def _boom(file_bytes, item_code):
        raise RuntimeError("Invalid image file")

    monkeypatch.setattr("app.services.bulk_upload.upload_item_image", _boom)

    rows = [{"item_code": "IMG-FAIL", "item_name": "Bad Image Item", "category_1": "", "category_2": "", "unit": "pcs", "rate": 10, "quantity_in_stock": 5, "min_threshold": 2}]
    file_bytes = _xlsx_bytes(rows)
    images_zip = _zip_bytes({"IMG-FAIL.jpg": b"not-a-real-image"})

    resp = client.post(
        "/api/v1/inventory/bulk-upload",
        files={
            "file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            "images_zip": ("images.zip", images_zip, "application/zip"),
        },
    )
    result = resp.json()
    assert result["inserted"] == 1
    assert result["skipped"] == 0
    assert result["errors"] == []
    assert result["images_matched"] == 0
    assert result["images_unmatched"] == 1

    # the item itself really was created, just without an image
    created = client.get("/api/v1/inventory/IMG-FAIL")
    assert created.status_code == 200
    assert created.json()["cloudinary_image_url"] is None


def test_bulk_upload_without_images_zip_reports_zero(client):
    rows = [{"item_code": "NOIMG", "item_name": "No Zip At All", "category_1": "", "category_2": "", "unit": "pcs", "rate": 10, "quantity_in_stock": 5, "min_threshold": 2}]
    file_bytes = _xlsx_bytes(rows)

    resp = client.post(
        "/api/v1/inventory/bulk-upload",
        files={"file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    result = resp.json()
    assert result["images_matched"] == 0
    assert result["images_unmatched"] == 0
