"""Section 5.4.E, Screen 18 — Bank Accounts. Admin-only full CRUD over the
bank_accounts table that's existed since Phase 1 (db/schema.sql) but only
ever had a read-only, active-only, names-only view via
GET /master-data/bank-accounts (Record Payment's bank picker, Section 5.0) —
this is the actual management screen behind Section 3.2's 'Admin only' route."""

from supabase import Client

from app.models.bank_account import BankAccountCreate, BankAccountOut, BankAccountUpdate


class BankAccountNotFoundError(Exception):
    pass


def row_to_out(row: dict) -> BankAccountOut:
    return BankAccountOut(
        id=row["id"],
        bank_name=row["bank_name"],
        account_note=row.get("account_note"),
        is_active=row.get("is_active", True),
    )


def list_bank_accounts(supabase: Client) -> list[BankAccountOut]:
    resp = supabase.table("bank_accounts").select("*").order("bank_name", desc=False).execute()
    return [row_to_out(row) for row in resp.data]


def create_bank_account(supabase: Client, data: BankAccountCreate) -> BankAccountOut:
    payload = {"bank_name": data.bank_name, "account_note": data.account_note, "is_active": True}
    resp = supabase.table("bank_accounts").insert(payload).execute()
    return row_to_out(resp.data[0])


def update_bank_account(supabase: Client, bank_account_id: str, data: BankAccountUpdate) -> BankAccountOut:
    existing = supabase.table("bank_accounts").select("*").eq("id", bank_account_id).limit(1).execute()
    if not existing.data:
        raise BankAccountNotFoundError(f"Bank account '{bank_account_id}' not found")

    changes = data.model_dump(exclude_unset=True)
    if not changes:
        return row_to_out(existing.data[0])

    resp = supabase.table("bank_accounts").update(changes).eq("id", bank_account_id).execute()
    return row_to_out(resp.data[0])
