"""Section 5.4.C — Expenses module. No balance chain (not a party ledger), no
harness math hook (there's no rate*qty formula here — amount is entered directly)."""

from supabase import Client

from app.models.expense import ExpenseCreate, ExpenseOut
from app.services.master_data import lookup_id_by_name
from app.services.party_service import require_party


def _particular_names(supabase: Client) -> dict[str, str]:
    """Section 5.4.F: /master-data/particulars only ever returns names (other
    callers, e.g. Record Payment's Method dropdown, only ever need the name to
    submit a create call) — this is the read-side id->name map so the
    Expenses list can show 'Fuel' instead of a bare UUID, without changing
    that shared endpoint's response shape for its existing consumers."""
    return {row["id"]: row["name"] for row in supabase.table("particulars").select("*").execute().data}


def row_to_out(row: dict, particular_names: dict[str, str] | None = None) -> ExpenseOut:
    particular_id = row.get("particular_id")
    return ExpenseOut(
        id=row["id"],
        serial_number=row.get("serial_number"),
        expense_date=row["expense_date"],
        party_id=row.get("party_id"),
        description=row.get("description"),
        amount=float(row["amount"]),
        particular_id=particular_id,
        particular_name=(particular_names or {}).get(particular_id) if particular_id else None,
        created_at=row.get("created_at"),
    )


def create_expense(supabase: Client, data: ExpenseCreate) -> ExpenseOut:
    if data.party_id is not None:
        require_party(supabase, data.party_id)  # Section 5.4.C: party is optional, but if given must be real

    particular_id = lookup_id_by_name(supabase, "particulars", data.particular) if data.particular else None

    payload = {
        "expense_date": data.expense_date.isoformat(),
        "party_id": data.party_id,
        "description": data.description,
        "amount": str(data.amount),
        "particular_id": particular_id,
    }
    resp = supabase.table("expenses").insert(payload).execute()
    return row_to_out(resp.data[0], _particular_names(supabase))


def list_expenses(supabase: Client, start_date=None, end_date=None) -> list[ExpenseOut]:
    query = supabase.table("expenses").select("*")
    if start_date is not None:
        query = query.gte("expense_date", start_date.isoformat())
    if end_date is not None:
        query = query.lte("expense_date", end_date.isoformat())
    resp = query.order("expense_date", desc=True).execute()
    particular_names = _particular_names(supabase)
    return [row_to_out(row, particular_names) for row in resp.data]
