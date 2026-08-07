"""A tiny in-memory stand-in for the supabase-py client, purpose-built for the
query patterns app/services/inventory_service.py and bulk_upload.py actually use
(table/select/insert/update/delete/eq/ilike/or_/order/range/limit/execute, plus
the categories_1/categories_2/units foreign-key embedding).

Not a general PostgREST emulator — just enough to exercise Section 10's Inventory
CRUD logic in tests without a live Supabase project, per Section 12.0 layer 2
("Integration tests ... against a real (test) Postgres instance") until real
Supabase credentials are configured (the .env is currently placeholders only).
"""

import uuid
from datetime import datetime, timezone


class FakeResponse:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class FakeQuery:
    def __init__(self, store, table_name, mode="select", select_expr="*"):
        self.store = store
        self.table_name = table_name
        self.mode = mode
        self.select_expr = select_expr
        self.filters: list[tuple[str, str, str]] = []  # (op, column, value)
        self.or_filters: list[tuple[str, str]] = []  # (column, value) ilike-style, OR'd together
        self._limit: int | None = None
        self._range: tuple[int, int] | None = None
        self._order: list[tuple[str, bool]] = []
        self._payload: dict | None = None
        self._count_mode: str | None = None

    def select(self, expr: str = "*", count: str | None = None):
        self.select_expr = expr
        self._count_mode = count
        return self

    # -- filters -----------------------------------------------------------
    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def neq(self, column, value):
        self.filters.append(("neq", column, value))
        return self

    def ilike(self, column, value):
        # Keep the raw %wildcard% markers — _apply_filters decides substring
        # vs. exact match from their presence (real Postgres ILIKE semantics).
        self.filters.append(("ilike", column, value))
        return self

    def or_(self, expr: str):
        # expr like "item_name.ilike.%foo%,item_code.ilike.%foo%"
        for clause in expr.split(","):
            column, _op, pattern = clause.split(".", 2)
            self.or_filters.append((column, pattern.strip("%").lower()))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def order(self, column, desc=False):
        # Real postgrest chains multiple .order() calls into a multi-column
        # ORDER BY (first call = primary key, later calls = tiebreaks) — mirror
        # that here via multiple stable sort passes in execute(), applied from
        # least to most significant so earlier .order() calls win ties.
        self._order.append((column, desc))
        return self

    def is_(self, column, value):
        # value is the postgrest-style literal: "null" / "true" / "false"
        target = {"null": None, "true": True, "false": False}.get(value, value)
        self.filters.append(("is", column, target))
        return self

    def gte(self, column, value):
        self.filters.append(("gte", column, value))
        return self

    def lte(self, column, value):
        self.filters.append(("lte", column, value))
        return self

    # -- mutation entry points ----------------------------------------------
    def insert(self, payload: dict):
        self.mode = "insert"
        self._payload = payload
        return self

    def update(self, payload: dict):
        self.mode = "update"
        self._payload = payload
        return self

    def delete(self):
        self.mode = "delete"
        return self

    # -- execution -----------------------------------------------------------
    def execute(self):
        rows = self.store.tables[self.table_name]

        if self.mode == "insert":
            row = dict(self._payload)
            row.setdefault("id", str(uuid.uuid4()))
            row.setdefault("created_at", datetime.now(timezone.utc).isoformat())
            row.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
            row.setdefault("cloudinary_image_url", None)
            row.setdefault("cloudinary_public_id", None)
            self.store._seq += 1
            row["_seq"] = self.store._seq
            if self.table_name == "expenses":
                self.store._expense_serial += 1
                row.setdefault("serial_number", self.store._expense_serial)
            rows.append(row)
            return FakeResponse(data=[row])

        matched = self._apply_filters(rows)

        if self.mode == "update":
            for row in matched:
                row.update(self._payload)
                row["updated_at"] = datetime.now(timezone.utc).isoformat()
            return FakeResponse(data=matched)

        if self.mode == "delete":
            for row in matched:
                rows.remove(row)
            return FakeResponse(data=matched)

        # select
        total = len(matched)
        for column, desc in reversed(self._order):
            matched = sorted(matched, key=lambda r, c=column: (r.get(c) or "", r.get("_seq", 0)), reverse=desc)
        if self._range:
            start, end = self._range
            matched = matched[start : end + 1]
        if self._limit is not None:
            matched = matched[: self._limit]

        result = [self._project(r) for r in matched]
        count = total if self._count_mode == "exact" else None
        return FakeResponse(data=result, count=count)

    # -- helpers -----------------------------------------------------------
    def _apply_filters(self, rows):
        result = []
        for row in rows:
            ok = True
            for op, column, value in self.filters:
                if op == "eq" and row.get(column) != value:
                    ok = False
                elif op == "neq" and row.get(column) == value:
                    ok = False
                elif op == "ilike":
                    cell = (row.get(column) or "").lower()
                    pattern = value.lower()
                    matches = (pattern.strip("%") in cell) if pattern.startswith("%") and pattern.endswith("%") else cell == pattern
                    if not matches:
                        ok = False
                elif op == "is" and row.get(column) != value:
                    ok = False
                elif op == "gte" and (row.get(column) is None or str(row.get(column)) < str(value)):
                    ok = False
                elif op == "lte" and (row.get(column) is None or str(row.get(column)) > str(value)):
                    ok = False
            if ok and self.or_filters:
                ok = any(value in (row.get(column) or "").lower() for column, value in self.or_filters)
            if ok:
                result.append(row)
        return result

    def _project(self, row: dict) -> dict:
        if self.table_name != "inventory_items" or "category_1:categories_1" not in self.select_expr:
            return dict(row)

        out = dict(row)
        out["category_1"] = self.store.find_by_id("categories_1", row.get("category_1_id"))
        out["category_2"] = self.store.find_by_id("categories_2", row.get("category_2_id"))
        out["unit_ref"] = self.store.find_by_id("units", row.get("unit"))
        return out


class FakeSupabaseClient:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {
            "parties": [],
            "users": [],
            "units": [],
            "categories_1": [],
            "categories_2": [],
            "particulars": [],
            "bank_accounts": [],
            "party_item_rates": [],
            "inventory_items": [],
            "customer_ledgers": [],
            "purchases": [],
            "expenses": [],
            "invoice_line_items": [],
            "purchase_line_items": [],
            "login_requests": [],
            "app_settings": [],
            "inbox_messages": [],
            "notification_preferences": [],
            "activity_log": [],
            "stock_adjustments": [],
            "sales_returns": [],
            "delivery_challans": [],
        }
        self._seq = 0
        self._expense_serial = 0

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)

    def find_by_id(self, table_name: str, row_id: str | None) -> dict | None:
        if not row_id:
            return None
        for row in self.tables[table_name]:
            if row["id"] == row_id:
                return {"name": row["name"]}
        return None

    # convenience for test setup
    def seed(self, table_name: str, name: str, name_field: str = "name", **extra_fields) -> str:
        row_id = str(uuid.uuid4())
        self.tables[table_name].append({"id": row_id, name_field: name, **extra_fields})
        return row_id
