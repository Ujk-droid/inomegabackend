"""Section 8 — the six Analytics queries. Every function reads directly from
the same live tables the rest of the app writes to (customer_ledgers,
invoice_line_items, inventory_items, parties, particulars) — there is no
separate cached/duplicated reporting dataset, so a new sale or payment shows
up here immediately, matching Section 12.1's explicit requirement.

Joins across invoice_line_items / customer_ledgers / inventory_items are done
in Python rather than relying on postgrest embedding syntax, so this works
identically against the real Supabase client and the in-memory fake used in
tests.

Charts moved from server-rendered Matplotlib PNGs to real, live
@gravity-ui/charts on the frontend (see progress.md) — every function here
now returns only the real numbers; there is no image generation or
Cloudinary upload left in this file."""

from collections import defaultdict
from datetime import date as date_cls

from supabase import Client


def _in_range(value_date: str | date_cls | None, start: date_cls | None, end: date_cls | None) -> bool:
    if value_date is None:
        return False
    d = value_date if isinstance(value_date, date_cls) else date_cls.fromisoformat(str(value_date))
    if start and d < start:
        return False
    if end and d > end:
        return False
    return True


# ── 1. Monthly Sales & Revenue (area, frontend) ─────────────────────────────


def monthly_sales_revenue(supabase: Client, start_date: date_cls | None = None, end_date: date_cls | None = None) -> dict:
    resp = (
        supabase.table("customer_ledgers")
        .select("*")
        .eq("txn_type", "sale")
        .eq("invoice_state", "finalized")
        .is_("deleted_at", "null")
        .execute()
    )

    totals: dict[str, float] = defaultdict(float)
    for row in resp.data:
        if not _in_range(row.get("transaction_date"), start_date, end_date):
            continue
        month = str(row["transaction_date"])[:7]  # 'YYYY-MM'
        totals[month] += float(row["total_amount"])

    months = sorted(totals.keys())
    data = [{"month": m, "revenue": round(totals[m], 2)} for m in months]
    return {"data": data}


# ── 2. Top 5 Selling Scale Models (vertical bar, frontend) ──────────────────


def top_selling_models(
    supabase: Client, start_date: date_cls | None = None, end_date: date_cls | None = None, limit: int = 5
) -> dict:
    ledgers = (
        supabase.table("customer_ledgers")
        .select("*")
        .eq("invoice_state", "finalized")
        .is_("deleted_at", "null")
        .execute()
        .data
    )
    ledger_by_id = {row["id"]: row for row in ledgers}

    items = supabase.table("inventory_items").select("*").execute().data
    item_name_by_code = {row["item_code"]: row["item_name"] for row in items}

    line_items = supabase.table("invoice_line_items").select("*").execute().data

    qty_by_name: dict[str, int] = defaultdict(int)
    for line in line_items:
        parent = ledger_by_id.get(line["ledger_id"])
        if parent is None or not _in_range(parent.get("transaction_date"), start_date, end_date):
            continue
        name = item_name_by_code.get(line["item_code"], line["item_code"])
        qty_by_name[name] += line["qty"]

    top = sorted(qty_by_name.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    data = [{"item_name": name, "quantity_sold": qty} for name, qty in top]
    return {"data": data}


# ── 3. Customer Debt / Ledger Balance (pie, frontend) ────────────────────────


def customer_debt_balance(supabase: Client) -> dict:
    parties = supabase.table("parties").select("*").execute().data
    customer_parties = [p for p in parties if p.get("party_type") in ("customer", "both")]

    data = []
    for party in customer_parties:
        resp = (
            supabase.table("customer_ledgers")
            .select("current_balance")
            .eq("party_id", party["id"])
            .is_("deleted_at", "null")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        balance = float(resp.data[0]["current_balance"]) if resp.data else 0.0
        if balance > 0:
            data.append({"party_name": party["party_name"], "current_balance": round(balance, 2)})

    return {"data": data}


# ── 4. Low Stock Items (horizontal bar, frontend) ────────────────────────────


def low_stock_items(supabase: Client) -> dict:
    resp = supabase.table("inventory_items").select("*").execute()
    below = [row for row in resp.data if row["quantity_in_stock"] <= row["min_threshold"]]
    below.sort(key=lambda row: row["min_threshold"] - row["quantity_in_stock"], reverse=True)

    data = [
        {"item_code": row["item_code"], "quantity_in_stock": row["quantity_in_stock"], "min_threshold": row["min_threshold"]}
        for row in below
    ]
    return {"data": data}


# ── 5. Payment Method Breakdown (donut, frontend) ────────────────────────────


def payment_method_breakdown(supabase: Client, start_date: date_cls | None = None, end_date: date_cls | None = None) -> dict:
    resp = supabase.table("customer_ledgers").select("*").eq("txn_type", "receiving").is_("deleted_at", "null").execute()
    particulars = {row["id"]: row["name"] for row in supabase.table("particulars").select("*").execute().data}

    totals: dict[str, float] = defaultdict(float)
    for row in resp.data:
        if not _in_range(row.get("transaction_date"), start_date, end_date):
            continue
        method = particulars.get(row.get("particular_id"), "Unknown")
        totals[method] += float(row["total_amount"])

    data = [{"method": method, "total": round(total, 2)} for method, total in totals.items()]
    return {"data": data}


# ── 6. Category-wise Sales (waterfall, frontend) ─────────────────────────────


def category_wise_sales(supabase: Client, start_date: date_cls | None = None, end_date: date_cls | None = None) -> dict:
    ledgers = (
        supabase.table("customer_ledgers")
        .select("*")
        .eq("invoice_state", "finalized")
        .is_("deleted_at", "null")
        .execute()
        .data
    )
    ledger_by_id = {row["id"]: row for row in ledgers}

    items = supabase.table("inventory_items").select("*").execute().data
    category_id_by_code = {row["item_code"]: row.get("category_1_id") for row in items}
    category_name_by_id = {row["id"]: row["name"] for row in supabase.table("categories_1").select("*").execute().data}

    line_items = supabase.table("invoice_line_items").select("*").execute().data

    totals: dict[str, float] = defaultdict(float)
    for line in line_items:
        parent = ledger_by_id.get(line["ledger_id"])
        if parent is None or not _in_range(parent.get("transaction_date"), start_date, end_date):
            continue
        category_id = category_id_by_code.get(line["item_code"])
        category_name = category_name_by_id.get(category_id, "Uncategorized")
        totals[category_name] += float(line["line_total"])

    data = [{"category": name, "total": round(total, 2)} for name, total in totals.items()]
    return {"data": data}
