"""Shared line-item plumbing for invoice_line_items and purchase_line_items —
same shape, same rules, different parent table/column. Used by ledger_service.py
and purchase_service.py so the multi-item logic (Section 5's fix) lives once."""

from supabase import Client

from app.services import ledger_hooks, ledger_math
from app.services.inventory_service import ItemNotFoundError, fetch_item_by_code


def resolve_and_verify_lines(supabase: Client, line_items: list) -> list[dict]:
    """Resolves each line's rate (catalog default if omitted), computes
    line_total, and runs Section 7.3's per-line math check before anything is
    written. Returns plain dicts: item_code, qty, rate, line_total.

    `line_items` is duck-typed — anything with .item_code/.qty/.rate attributes
    (both app.models.ledger.LineItemCreate and app.models.purchase.LineItemCreate
    satisfy this)."""
    resolved = []
    for li in line_items:
        item = fetch_item_by_code(supabase, li.item_code)
        if item is None:
            raise ItemNotFoundError(f"Item code '{li.item_code}' not found")
        rate = li.rate if li.rate is not None else float(item["rate"])
        line_total = ledger_math.compute_line_total(rate, li.qty)
        ledger_hooks.verify_line_math(rate, li.qty, line_total)
        resolved.append({"item_code": li.item_code.upper(), "qty": li.qty, "rate": rate, "line_total": line_total})
    return resolved


def insert_line_items(supabase: Client, table: str, parent_column: str, parent_id: str, resolved_lines: list[dict]) -> None:
    for line_number, line in enumerate(resolved_lines, start=1):
        supabase.table(table).insert(
            {
                parent_column: parent_id,
                "item_code": line["item_code"],
                "qty": line["qty"],
                "rate": str(line["rate"]),
                "line_total": str(line["line_total"]),
                "line_number": line_number,
            }
        ).execute()


def fetch_line_items(supabase: Client, table: str, parent_column: str, parent_id: str) -> list[dict]:
    resp = supabase.table(table).select("*").eq(parent_column, parent_id).order("line_number", desc=False).execute()
    return resp.data


def replace_line_items(supabase: Client, table: str, parent_column: str, parent_id: str, resolved_lines: list[dict]) -> None:
    """Draft edits (Section 5.1: fully editable) replace the whole line-item set
    rather than patching individual lines — simplest correct semantics for a
    document that isn't locked yet."""
    supabase.table(table).delete().eq(parent_column, parent_id).execute()
    insert_line_items(supabase, table, parent_column, parent_id, resolved_lines)
