"""Section 16.2 — Stock Adjustment (physical count reconciliation). Every
adjustment is permanent (Section 5.2's retention rule) — never edited, only
further adjustments if a mistake is made correcting a mistake."""

from supabase import Client

from app.models.stock_adjustment import VALID_REASONS, StockAdjustmentCreate, StockAdjustmentOut
from app.services import activity_log_service
from app.services.inventory_service import ItemNotFoundError, fetch_item_by_code


class InvalidReasonError(Exception):
    pass


def _row_to_out(row: dict) -> StockAdjustmentOut:
    return StockAdjustmentOut(
        id=row["id"],
        item_code=row["item_code"],
        previous_qty=row["previous_qty"],
        counted_qty=row["counted_qty"],
        delta=row["delta"],
        reason=row["reason"],
        note=row.get("note"),
        adjusted_by=row["adjusted_by"],
        created_at=row.get("created_at"),
    )


def create_adjustment(
    supabase: Client, item_code: str, data: StockAdjustmentCreate, user_id: str
) -> StockAdjustmentOut:
    if data.reason not in VALID_REASONS:
        raise InvalidReasonError(f"reason must be one of {sorted(VALID_REASONS)}")

    item = fetch_item_by_code(supabase, item_code)
    if item is None:
        raise ItemNotFoundError(f"Item code '{item_code}' not found")

    previous_qty = item["quantity_in_stock"]
    delta = data.counted_qty - previous_qty

    payload = {
        "item_code": item_code.upper(),
        "previous_qty": previous_qty,
        "counted_qty": data.counted_qty,
        "delta": delta,
        "reason": data.reason,
        "note": data.note,
        "adjusted_by": user_id,
    }
    resp = supabase.table("stock_adjustments").insert(payload).execute()
    supabase.table("inventory_items").update({"quantity_in_stock": data.counted_qty}).eq(
        "item_code", item_code.upper()
    ).execute()

    sign = "+" if delta >= 0 else ""
    reason_note = f" ({data.reason}{': ' + data.note if data.note else ''})"
    activity_log_service.log_activity(
        supabase,
        user_id,
        "stock_adjustment",
        f"Adjusted {item_code.upper()} stock from {previous_qty} to {data.counted_qty} ({sign}{delta}){reason_note}",
    )

    return _row_to_out(resp.data[0])


def list_adjustments_for_item(supabase: Client, item_code: str) -> list[StockAdjustmentOut]:
    resp = (
        supabase.table("stock_adjustments")
        .select("*")
        .eq("item_code", item_code.upper())
        .order("created_at", desc=True)
        .execute()
    )
    return [_row_to_out(row) for row in resp.data]
