import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from supabase import Client

from app.database import get_supabase
from app.dependencies import get_current_user, require_admin
from app.models.inventory import (
    BulkUploadResult,
    InventoryItemCreate,
    InventoryItemOut,
    InventoryListResponse,
)
from app.models.stock_adjustment import StockAdjustmentCreate, StockAdjustmentOut
from app.services import activity_log_service
from app.services.bulk_upload import build_template_bytes, process_bulk_dataframe, read_upload_dataframe
from app.services.cloudinary_client import delete_item_image, upload_item_image
from app.services.inventory_service import (
    DuplicateItemCodeError,
    ItemNotFoundError,
    UnknownReferenceError,
    create_item,
    delete_item,
    fetch_item_by_code,
    list_items,
    row_to_out,
    update_item,
)
from app.services.stock_adjustment_service import (
    InvalidReasonError,
    create_adjustment,
    list_adjustments_for_item,
)

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


@router.get("/bulk-upload/template")
def download_template(user: dict = Depends(get_current_user)):
    """Section 6, Screen 3 — 'Download Template' link in the Bulk Upload modal."""
    content = build_template_bytes()
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=inventory_bulk_upload_template.xlsx"},
    )


@router.post("/bulk-upload", response_model=BulkUploadResult)
async def bulk_upload(
    file: UploadFile = File(...),
    dry_run: bool = Form(False),
    images_zip: UploadFile | None = File(None),
    admin: dict = Depends(require_admin),
    supabase: Client = Depends(get_supabase),
):
    """Section 10 (2) + Section 6 Screen 3 Step 2-4. Supports up to 1,500 rows in one
    file. Admin-only (Section 3: 'Staff do not see the Bulk Upload button at all').
    Step 2's preview calls this with dry_run=true — same parse/validate path as
    the real commit, so the preview counts can never drift from what Step 3
    actually imports; only the create_item/update_item writes are skipped.

    Section 10.2b — images_zip is optional: a .zip of product images, matched
    to rows by filename (minus extension) == item_code."""
    if not (file.filename.lower().endswith(".xlsx") or file.filename.lower().endswith(".csv")):
        raise HTTPException(status_code=400, detail="Only .xlsx or .csv files are accepted")

    contents = await file.read()
    try:
        df = read_upload_dataframe(file.filename, contents)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not parse file: {exc}") from exc

    if len(df) > 1500:
        raise HTTPException(status_code=400, detail=f"File has {len(df)} rows — the limit is 1,500 (Section 10)")

    if images_zip is not None and not images_zip.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Product images must be uploaded as a single .zip file")

    images_zip_bytes = await images_zip.read() if images_zip is not None else None
    # process_bulk_dataframe is synchronous and, when images_zip is present,
    # does a real sequential network call (Cloudinary upload + Supabase
    # update) per matched image. Calling it directly here would block
    # uvicorn's single event loop for that whole duration — long enough,
    # for a real multi-image batch, that the connection gets reset before
    # a response is ever sent (confirmed live: a 12-image batch blocked the
    # loop for 30+ seconds even with 1-pixel stub images). run_in_threadpool
    # keeps the event loop free to service the connection while this runs.
    return await run_in_threadpool(
        process_bulk_dataframe, supabase, df, dry_run=dry_run, images_zip=images_zip_bytes
    )


@router.post("/create", response_model=InventoryItemOut, status_code=201)
async def create_inventory_item(
    item_code: str = Form(...),
    item_name: str = Form(...),
    unit: str = Form(...),
    rate: float = Form(...),
    quantity_in_stock: int = Form(0),
    min_threshold: int = Form(5),
    category_1: str | None = Form(None),
    category_2: str | None = Form(None),
    image: UploadFile | None = File(None),
    admin: dict = Depends(require_admin),
    supabase: Client = Depends(get_supabase),
):
    """Section 10 (1) — manual, one at a time. On success: item appears in the
    Inventory table immediately (the caller re-fetches the list; no server-side
    cache to invalidate). On duplicate item_code: 409 with an inline-friendly message.
    Admin-only (Section 3: Staff get 'Read-only stock view')."""
    try:
        item = InventoryItemCreate(
            item_code=item_code,
            item_name=item_name,
            unit=unit,
            rate=rate,
            quantity_in_stock=quantity_in_stock,
            min_threshold=min_threshold,
            category_1=category_1,
            category_2=category_2,
        )
        created = create_item(supabase, item)
    except DuplicateItemCodeError as exc:
        raise HTTPException(status_code=409, detail="This item code already exists") from exc
    except UnknownReferenceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if image is not None:
        image_bytes = await image.read()
        url, public_id = upload_item_image(image_bytes, created.item_code)
        supabase.table("inventory_items").update(
            {"cloudinary_image_url": url, "cloudinary_public_id": public_id}
        ).eq("item_code", created.item_code).execute()
        created.cloudinary_image_url = url
        created.cloudinary_public_id = public_id

    return created


@router.get("", response_model=InventoryListResponse)
def list_inventory_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str | None = Query(None, description="Matches item_code or item_name"),
    category_1: str | None = Query(None),
    category_2: str | None = Query(None),
    user: dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Section 10 READ — search + server-side pagination, up to 1,500 rows."""
    try:
        items, total = list_items(supabase, page, page_size, search, category_1, category_2)
    except UnknownReferenceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return InventoryListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/{item_code}", response_model=InventoryItemOut)
def get_inventory_item(
    item_code: str, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    row = fetch_item_by_code(supabase, item_code)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Item code '{item_code}' not found")
    return row_to_out(row)


@router.put("/{item_code}", response_model=InventoryItemOut)
async def update_inventory_item(
    item_code: str,
    item_name: str | None = Form(None),
    unit: str | None = Form(None),
    rate: float | None = Form(None),
    quantity_in_stock: int | None = Form(None),
    min_threshold: int | None = Form(None),
    category_1: str | None = Form(None),
    category_2: str | None = Form(None),
    image: UploadFile | None = File(None),
    admin: dict = Depends(require_admin),
    supabase: Client = Depends(get_supabase),
):
    """Section 10 UPDATE — live price/rate updates and stock adjustment, one item
    at a time. Admin-only (Section 3: Staff 'Cannot: edit rates')."""
    try:
        updated = update_item(
            supabase,
            item_code,
            {
                "item_name": item_name,
                "unit": unit,
                "rate": rate,
                "quantity_in_stock": quantity_in_stock,
                "min_threshold": min_threshold,
                "category_1": category_1,
                "category_2": category_2,
            },
        )
    except ItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UnknownReferenceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if image is not None:
        image_bytes = await image.read()
        url, public_id = upload_item_image(image_bytes, updated.item_code)
        supabase.table("inventory_items").update(
            {"cloudinary_image_url": url, "cloudinary_public_id": public_id}
        ).eq("item_code", updated.item_code).execute()
        updated.cloudinary_image_url = url
        updated.cloudinary_public_id = public_id

    return updated


@router.delete("/{item_code}", status_code=204)
def delete_inventory_item(
    item_code: str, admin: dict = Depends(require_admin), supabase: Client = Depends(get_supabase)
):
    """Section 10 DELETE — purge from Supabase + remove the Cloudinary asset.
    Admin-only in the app's RBAC (Section 3) — now enforced.
    One item at a time only — no bulk-delete route exists, matching Section 5.2's
    no-bulk-delete harness rule applied here too."""
    try:
        public_id = delete_item(supabase, item_code)
    except ItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if public_id:
        delete_item_image(public_id)

    activity_log_service.log_activity(supabase, admin["id"], "item_deleted", f"Deleted inventory item '{item_code}'")


@router.post("/{item_code}/stock-adjustments", response_model=StockAdjustmentOut, status_code=201)
def create_stock_adjustment_endpoint(
    item_code: str,
    data: StockAdjustmentCreate,
    admin: dict = Depends(require_admin),
    supabase: Client = Depends(get_supabase),
):
    """Section 16.2 — physical count reconciliation, Admin-only, from Item
    Detail. Permanent once written (Section 5.2) — no edit/delete route exists."""
    try:
        return create_adjustment(supabase, item_code, data, admin["id"])
    except ItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidReasonError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{item_code}/stock-adjustments", response_model=list[StockAdjustmentOut])
def list_stock_adjustments_endpoint(
    item_code: str, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    return list_adjustments_for_item(supabase, item_code)
