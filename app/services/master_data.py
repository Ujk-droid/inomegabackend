"""Shared lookups against the admin-editable master tables (Section 5.4.F/E/G):
categories_1, categories_2, particulars, bank_accounts, units."""

from supabase import Client


class UnknownReferenceError(Exception):
    """A name given on a row doesn't exist in its master table — these are
    admin-managed lists, so a typo surfaces as an explicit error rather than
    silently creating a new master-table row."""


def lookup_id_by_name(supabase: Client, table: str, name: str) -> str:
    resp = supabase.table(table).select("id").ilike("name", name).limit(1).execute()
    if not resp.data:
        raise UnknownReferenceError(f"'{name}' was not found in {table} — add it there first")
    return resp.data[0]["id"]


def lookup_bank_account_id(supabase: Client, bank_name: str) -> str:
    """Record Payment's bank picker (Section 5.4.E) — only resolves against
    *active* banks. The Bank Accounts screen hides a deactivated bank from
    this same picker client-side, but that's cosmetic only; this is the
    actual enforcement, so a stale client or a direct API call can't still
    record a payment against a bank an Admin already deactivated."""
    resp = (
        supabase.table("bank_accounts")
        .select("id")
        .ilike("bank_name", bank_name)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    if not resp.data:
        raise UnknownReferenceError(f"'{bank_name}' was not found in bank_accounts — add it there first")
    return resp.data[0]["id"]
