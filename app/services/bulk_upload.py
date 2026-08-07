"""Section 10 / Section 6 Screen 3 — Bulk Excel/CSV upload for Inventory.
Section 10.2b adds the optional images .zip alongside the spreadsheet."""

import io
import logging
import zipfile
from pathlib import PurePosixPath

import pandas as pd
from supabase import Client

from app.models.inventory import BULK_UPLOAD_COLUMNS, BulkUploadPreviewRow, BulkUploadResult
from app.services.cloudinary_client import upload_item_image
from app.services.inventory_service import (
    UnknownReferenceError,
    create_item,
    fetch_item_by_code,
    parse_and_validate_row,
    update_item,
)

logger = logging.getLogger(__name__)
# Nothing in this codebase configures Python's logging module (no
# basicConfig, no per-logger setup anywhere) — a plain module-level logger
# would silently rely on the interpreter's WARNING-level "handler of last
# resort," which drops INFO entirely. This feature's whole point is
# terminal-visible diagnostics for a 0-images-matched report, so this
# logger configures its own handler/level directly rather than depending on
# app-wide config existing; propagate=False keeps it from ever double
# -printing if root logging does get configured later.
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s: %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
IMAGE_FILENAMES_PREVIEW_LIMIT = 50


def _read_images_by_item_code(images_zip: bytes | None) -> tuple[dict[str, bytes], list[str]]:
    """Section 10.2b: 'each image's filename (minus extension) must exactly
    equal an item_code from the same Excel batch.' Keyed uppercase to match
    item_code's own normalization (InventoryItemBase.normalize_item_code).

    Real bug fixed here: only matched entries at the zip's root. Selecting a
    whole folder and choosing "Compress to ZIP" (the normal way someone
    would zip a batch of product photos, especially on Windows) nests every
    file under a folder entry — 'product-images/P-16-S-A-MK.jpg', not
    'P-16-S-A-MK.jpg' — and some zip tools (older WinZip builds, some
    PowerShell Compress-Archive configurations) write that separator as '\\'
    rather than the '/' the ZIP format spec calls for. `PurePosixPath` only
    ever treats '/' as a separator, so a '\\'-separated entry was previously
    read as one single (non-matching) filename containing a literal
    backslash. Normalizing '\\' to '/' before parsing, and always taking
    just the final path component, makes matching depend only on the
    filename itself — any folder nesting or separator style now behaves the
    same as a flat zip.

    Returns (images_by_code, all_image_filenames_seen) — the second is a
    diagnostic aid (Section 10.2b's own "never silent" convention): the raw,
    un-normalized entry names the reader treated as images, so a 0-matched
    result can be debugged from the API response alone instead of guessing."""
    if not images_zip:
        return {}, []
    images: dict[str, bytes] = {}
    filenames_seen: list[str] = []
    with zipfile.ZipFile(io.BytesIO(images_zip)) as zf:
        for name in zf.namelist():
            if name.endswith("/") or name.endswith("\\"):
                continue  # directory entry, not a file
            normalized = name.replace("\\", "/")
            path = PurePosixPath(normalized)
            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            filenames_seen.append(name)
            images[path.stem.strip().upper()] = zf.read(name)

    logger.info(
        "Bulk upload images_zip: found %d image file(s): %s",
        len(filenames_seen),
        filenames_seen[:IMAGE_FILENAMES_PREVIEW_LIMIT],
    )
    return images, filenames_seen


def build_template_bytes() -> bytes:
    df = pd.DataFrame(columns=BULK_UPLOAD_COLUMNS)
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return buffer.read()


def read_upload_dataframe(filename: str, contents: bytes) -> pd.DataFrame:
    buffer = io.BytesIO(contents)
    if filename.lower().endswith(".csv"):
        return pd.read_csv(buffer, dtype=str, keep_default_na=False)
    return pd.read_excel(buffer, dtype=str, engine="openpyxl", keep_default_na=False)


PREVIEW_ROW_LIMIT = 20


def process_bulk_dataframe(
    supabase: Client, df: pd.DataFrame, *, dry_run: bool = False, images_zip: bytes | None = None
) -> BulkUploadResult:
    """Section 6 Screen 3's Bulk Upload flow needs both a Step 2 preview (parse +
    validate against the real master tables and existing item_codes, but commit
    nothing) and a Step 3 confirm (the same logic, actually written). Both are
    this same function — dry_run only gates the create_item/update_item calls,
    so preview and commit can never silently disagree about which rows are
    inserts/updates/errors.

    Section 10.2b: images_zip matching only ever runs on the real commit
    (dry_run stays a pure, side-effect-free preview — no Cloudinary calls),
    after rows import, per the PRD's own stated processing order."""
    inserted = 0
    updated = 0
    skipped = 0
    errors: list = []
    preview_rows: list[BulkUploadPreviewRow] = []
    images_matched = 0
    images_unmatched = 0
    images_by_code, image_filenames_found = (
        _read_images_by_item_code(images_zip) if not dry_run else ({}, [])
    )

    missing_cols = [c for c in ("item_code", "item_name", "unit", "rate") if c not in df.columns]
    if missing_cols:
        errors.append({"row": 0, "item_code": None, "error": f"Missing required column(s): {', '.join(missing_cols)}"})
        return BulkUploadResult(
            total_rows=len(df), inserted=0, updated=0, skipped=len(df), errors=errors, committed=not dry_run
        )

    seen_codes: set[str] = set()

    for idx, raw_row in enumerate(df.to_dict(orient="records")):
        row_num = idx + 2  # header is row 1, data starts at row 2 in the spreadsheet
        item, err = parse_and_validate_row(raw_row, row_num)
        if err is not None:
            skipped += 1
            errors.append(err)
            if len(preview_rows) < PREVIEW_ROW_LIMIT:
                preview_rows.append(
                    BulkUploadPreviewRow(row=row_num, item_code=err.item_code, item_name=None, status="error", error=err.error)
                )
            continue

        if item.item_code in seen_codes:
            skipped += 1
            dup_error = "duplicate item_code within this file"
            errors.append({"row": row_num, "item_code": item.item_code, "error": dup_error})
            if len(preview_rows) < PREVIEW_ROW_LIMIT:
                preview_rows.append(
                    BulkUploadPreviewRow(
                        row=row_num, item_code=item.item_code, item_name=item.item_name, status="error", error=dup_error
                    )
                )
            continue
        seen_codes.add(item.item_code)

        try:
            existing = fetch_item_by_code(supabase, item.item_code)
            is_insert = existing is None
            if not dry_run:
                if is_insert:
                    create_item(supabase, item)
                else:
                    update_item(
                        supabase,
                        item.item_code,
                        {
                            "item_name": item.item_name,
                            "unit": item.unit,
                            "category_1": item.category_1,
                            "category_2": item.category_2,
                            "rate": item.rate,
                            "quantity_in_stock": item.quantity_in_stock,
                            "min_threshold": item.min_threshold,
                        },
                    )
            if is_insert:
                inserted += 1
            else:
                updated += 1

            if images_by_code:
                image_bytes = images_by_code.get(item.item_code)
                if image_bytes is not None:
                    # Best-effort, same convention as pdf_service._fetch_thumbnail —
                    # a bad/unreadable image must never turn an otherwise-successful
                    # row (already inserted/updated above) into a reported error.
                    try:
                        url, public_id = upload_item_image(image_bytes, item.item_code)
                        supabase.table("inventory_items").update(
                            {"cloudinary_image_url": url, "cloudinary_public_id": public_id}
                        ).eq("item_code", item.item_code).execute()
                        images_matched += 1
                    except Exception:  # noqa: BLE001
                        images_unmatched += 1
                else:
                    images_unmatched += 1

            if len(preview_rows) < PREVIEW_ROW_LIMIT:
                preview_rows.append(
                    BulkUploadPreviewRow(
                        row=row_num,
                        item_code=item.item_code,
                        item_name=item.item_name,
                        status="insert" if is_insert else "update",
                    )
                )
        except UnknownReferenceError as exc:
            skipped += 1
            errors.append({"row": row_num, "item_code": item.item_code, "error": str(exc)})
            if len(preview_rows) < PREVIEW_ROW_LIMIT:
                preview_rows.append(
                    BulkUploadPreviewRow(row=row_num, item_code=item.item_code, item_name=item.item_name, status="error", error=str(exc))
                )
        except Exception as exc:  # noqa: BLE001 — one bad row must never abort the whole batch
            skipped += 1
            errors.append({"row": row_num, "item_code": item.item_code, "error": str(exc)})
            if len(preview_rows) < PREVIEW_ROW_LIMIT:
                preview_rows.append(
                    BulkUploadPreviewRow(row=row_num, item_code=item.item_code, item_name=item.item_name, status="error", error=str(exc))
                )

    if image_filenames_found and images_matched == 0:
        logger.warning(
            "Bulk upload: images_zip had %d image file(s) but 0 matched any item_code. "
            "Filenames found: %s. item_codes expected: %s",
            len(image_filenames_found),
            image_filenames_found[:IMAGE_FILENAMES_PREVIEW_LIMIT],
            sorted(seen_codes)[:IMAGE_FILENAMES_PREVIEW_LIMIT],
        )

    return BulkUploadResult(
        total_rows=len(df),
        inserted=inserted,
        updated=updated,
        skipped=skipped,
        errors=errors,
        preview_rows=preview_rows,
        committed=not dry_run,
        images_matched=images_matched,
        images_unmatched=images_unmatched,
        image_filenames_found=image_filenames_found[:IMAGE_FILENAMES_PREVIEW_LIMIT],
    )
