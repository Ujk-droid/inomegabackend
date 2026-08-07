"""Section 10 — Inventory CRUD business logic.

Split from the router so the pure validation part (parse_and_validate_row) can be
unit-tested with no database/network involved (Section 12.0, layer 1), while the
DB-touching functions below it are exercised by the integration tests against a
mocked Supabase client (Section 12.0, layer 2) until real Supabase credentials
are configured.
"""

from supabase import Client

from app.models.inventory import BulkUploadRowError, InventoryItemCreate, InventoryItemOut

ITEM_SELECT = "*, category_1:categories_1(name), category_2:categories_2(name), unit_ref:units(name)"


class DuplicateItemCodeError(Exception):
    pass


class ItemNotFoundError(Exception):
    pass


class UnknownReferenceError(Exception):
    """Raised when a category_1/category_2/unit name given on a row doesn't exist
    in its master table. These are admin-managed lists (Section 5.4.F/G) — a typo
    here should surface as an explicit error, never silently create a new row in
    the master table."""


def parse_and_validate_row(row: dict, row_num: int) -> tuple[InventoryItemCreate | None, BulkUploadRowError | None]:
    """Pure validation, no I/O. Used by both bulk upload and (indirectly, via the
    same model) manual create."""
    item_code = str(row.get("item_code") or "").strip()
    item_name = str(row.get("item_name") or "").strip()
    unit = str(row.get("unit") or "").strip()

    if not item_code:
        return None, BulkUploadRowError(row=row_num, item_code=None, error="item_code is required")
    if not item_name:
        return None, BulkUploadRowError(row=row_num, item_code=item_code, error="item_name is required")
    if not unit:
        return None, BulkUploadRowError(row=row_num, item_code=item_code, error="unit is required")

    rate_raw = row.get("rate")
    try:
        rate = float(rate_raw)
    except (TypeError, ValueError):
        return None, BulkUploadRowError(row=row_num, item_code=item_code, error=f"rate '{rate_raw}' is not a number")
    if rate <= 0:
        return None, BulkUploadRowError(row=row_num, item_code=item_code, error="rate must be greater than 0")

    def _nonneg_int(value, field_name, default):
        if value is None or value == "":
            return default, None
        try:
            n = int(value)
        except (TypeError, ValueError):
            return None, f"{field_name} '{value}' is not a whole number"
        if n < 0:
            return None, f"{field_name} cannot be negative"
        return n, None

    qty, qty_err = _nonneg_int(row.get("quantity_in_stock"), "quantity_in_stock", 0)
    if qty_err:
        return None, BulkUploadRowError(row=row_num, item_code=item_code, error=qty_err)

    threshold, threshold_err = _nonneg_int(row.get("min_threshold"), "min_threshold", 5)
    if threshold_err:
        return None, BulkUploadRowError(row=row_num, item_code=item_code, error=threshold_err)

    category_1 = str(row["category_1"]).strip() if row.get("category_1") not in (None, "") else None
    category_2 = str(row["category_2"]).strip() if row.get("category_2") not in (None, "") else None

    item = InventoryItemCreate(
        item_code=item_code,
        item_name=item_name,
        category_1=category_1,
        category_2=category_2,
        unit=unit,
        rate=rate,
        quantity_in_stock=qty,
        min_threshold=threshold,
    )
    return item, None


def _lookup_id(supabase: Client, table: str, name: str) -> str:
    resp = supabase.table(table).select("id").ilike("name", name).limit(1).execute()
    if not resp.data:
        raise UnknownReferenceError(f"'{name}' was not found in {table} — add it there first")
    return resp.data[0]["id"]


def resolve_references(supabase: Client, item: InventoryItemCreate) -> dict:
    """Resolve category_1/category_2/unit names to their FK ids. Raises
    UnknownReferenceError if a name doesn't exist in its master table."""
    resolved = {"unit": _lookup_id(supabase, "units", item.unit)}
    if item.category_1:
        resolved["category_1_id"] = _lookup_id(supabase, "categories_1", item.category_1)
    if item.category_2:
        resolved["category_2_id"] = _lookup_id(supabase, "categories_2", item.category_2)
    return resolved


def row_to_out(row: dict) -> InventoryItemOut:
    category_1 = row.get("category_1")
    category_2 = row.get("category_2")
    unit_ref = row.get("unit_ref")
    quantity_in_stock = row["quantity_in_stock"]
    min_threshold = row["min_threshold"]
    return InventoryItemOut(
        id=row["id"],
        item_code=row["item_code"],
        item_name=row["item_name"],
        category_1=category_1["name"] if category_1 else None,
        category_2=category_2["name"] if category_2 else None,
        unit=unit_ref["name"] if unit_ref else None,
        rate=float(row["rate"]),
        quantity_in_stock=quantity_in_stock,
        min_threshold=min_threshold,
        is_low_stock=quantity_in_stock <= min_threshold,
        cloudinary_image_url=row.get("cloudinary_image_url"),
        cloudinary_public_id=row.get("cloudinary_public_id"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def fetch_item_by_code(supabase: Client, item_code: str) -> dict | None:
    resp = supabase.table("inventory_items").select(ITEM_SELECT).eq("item_code", item_code.upper()).limit(1).execute()
    return resp.data[0] if resp.data else None


def create_item(supabase: Client, item: InventoryItemCreate) -> InventoryItemOut:
    if fetch_item_by_code(supabase, item.item_code) is not None:
        raise DuplicateItemCodeError(f"Item code '{item.item_code}' already exists")

    refs = resolve_references(supabase, item)
    payload = {
        "item_code": item.item_code,
        "item_name": item.item_name,
        "rate": item.rate,
        "quantity_in_stock": item.quantity_in_stock,
        "min_threshold": item.min_threshold,
        **refs,
    }
    resp = supabase.table("inventory_items").insert(payload).execute()
    created = fetch_item_by_code(supabase, resp.data[0]["item_code"])
    return row_to_out(created)


class InsufficientStockError(Exception):
    pass


def adjust_stock(supabase: Client, item_code: str, delta: int) -> None:
    """Section 5.4.B: a Purchase increases quantity_in_stock; a finalized Sale
    decreases it ('the reverse of a Sale's decrease'). delta is signed:
    positive for a Purchase, negative for a Sale."""
    existing = fetch_item_by_code(supabase, item_code)
    if existing is None:
        raise ItemNotFoundError(f"Item code '{item_code}' not found")
    new_qty = existing["quantity_in_stock"] + delta
    if new_qty < 0:
        raise InsufficientStockError(
            f"Item '{item_code}' has {existing['quantity_in_stock']} in stock, cannot reduce by {-delta}"
        )
    supabase.table("inventory_items").update({"quantity_in_stock": new_qty}).eq("item_code", item_code.upper()).execute()


def update_item(supabase: Client, item_code: str, updates: dict) -> InventoryItemOut:
    existing = fetch_item_by_code(supabase, item_code)
    if existing is None:
        raise ItemNotFoundError(f"Item code '{item_code}' not found")

    payload: dict = {}
    if "item_name" in updates and updates["item_name"] is not None:
        payload["item_name"] = updates["item_name"]
    if "rate" in updates and updates["rate"] is not None:
        payload["rate"] = updates["rate"]
    if "quantity_in_stock" in updates and updates["quantity_in_stock"] is not None:
        payload["quantity_in_stock"] = updates["quantity_in_stock"]
    if "min_threshold" in updates and updates["min_threshold"] is not None:
        payload["min_threshold"] = updates["min_threshold"]
    if updates.get("unit"):
        payload["unit"] = _lookup_id(supabase, "units", updates["unit"])
    if updates.get("category_1"):
        payload["category_1_id"] = _lookup_id(supabase, "categories_1", updates["category_1"])
    if updates.get("category_2"):
        payload["category_2_id"] = _lookup_id(supabase, "categories_2", updates["category_2"])

    if payload:
        supabase.table("inventory_items").update(payload).eq("item_code", item_code.upper()).execute()

    return row_to_out(fetch_item_by_code(supabase, item_code))


def delete_item(supabase: Client, item_code: str) -> str | None:
    """Purges the row (Section 10 — DELETE is a hard purge, not a soft delete;
    that rule is specific to customer_ledgers, Section 5.2). Returns the
    cloudinary_public_id so the caller can also remove the CDN asset."""
    existing = fetch_item_by_code(supabase, item_code)
    if existing is None:
        raise ItemNotFoundError(f"Item code '{item_code}' not found")
    supabase.table("inventory_items").delete().eq("item_code", item_code.upper()).execute()
    return existing.get("cloudinary_public_id")


def list_items(
    supabase: Client,
    page: int = 1,
    page_size: int = 50,
    search: str | None = None,
    category_1: str | None = None,
    category_2: str | None = None,
) -> tuple[list[InventoryItemOut], int]:
    query = supabase.table("inventory_items").select(ITEM_SELECT, count="exact")
    if search:
        query = query.or_(f"item_name.ilike.%{search}%,item_code.ilike.%{search}%")
    if category_1:
        cat_id = _lookup_id(supabase, "categories_1", category_1)
        query = query.eq("category_1_id", cat_id)
    if category_2:
        cat_id = _lookup_id(supabase, "categories_2", category_2)
        query = query.eq("category_2_id", cat_id)

    start = (page - 1) * page_size
    end = start + page_size - 1
    resp = query.order("created_at", desc=True).range(start, end).execute()
    items = [row_to_out(row) for row in resp.data]
    total = resp.count if resp.count is not None else len(items)
    return items, total
