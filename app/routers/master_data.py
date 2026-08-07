from fastapi import APIRouter, Depends
from supabase import Client

from app.database import get_supabase
from app.dependencies import get_current_user
from app.models.master_data import BankAccountsOut, CategoriesOut, ParticularsOut, UnitsOut

router = APIRouter(prefix="/api/v1/master-data", tags=["master-data"])


@router.get("/categories", response_model=CategoriesOut)
def list_categories(user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)):
    """Section 6 Screen 3 — the Inventory List's Category 1/Category 2 filter
    tabs read these live master tables (Section 5.4.F: 'admin-editable') rather
    than hardcoding the screen prose's example names, so a category an Admin
    adds or renames shows up in the tabs without a frontend change. 'All' is a
    literal seeded row in categories_1 (db/schema.sql) but is excluded here —
    the frontend builds its own 'All Items' pseudo-tab that clears the filter
    rather than literally filtering category_1='All'."""
    cat1_rows = supabase.table("categories_1").select("name").execute().data
    cat2_rows = supabase.table("categories_2").select("name").execute().data
    category_1 = sorted(row["name"] for row in cat1_rows if row["name"] != "All")
    category_2 = sorted(row["name"] for row in cat2_rows)
    return CategoriesOut(category_1=category_1, category_2=category_2)


@router.get("/units", response_model=UnitsOut)
def list_units(user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)):
    """The Inventory 'Add New Item' modal's Unit field is validated against
    this same master table (inventory_service resolves it via
    master_data.lookup_id_by_name) — listing it here lets the field be a
    dropdown instead of a free-text field prone to the exact typo mismatch
    that lookup already guards against server-side."""
    rows = supabase.table("units").select("name").execute().data
    return UnitsOut(units=sorted(row["name"] for row in rows))


@router.get("/particulars", response_model=ParticularsOut)
def list_particulars(user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)):
    """Section 5.0 Record Payment's Method field (Cash/Cheque/Online/Bank Transfer)
    is a name resolved server-side against this same master table
    (ledger_service.record_payment -> master_data.lookup_id_by_name) — listing it
    here lets the field be a dropdown instead of free text, same reasoning as
    /units above."""
    rows = supabase.table("particulars").select("name").execute().data
    return ParticularsOut(particulars=sorted(row["name"] for row in rows))


@router.get("/bank-accounts", response_model=BankAccountsOut)
def list_bank_accounts(user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)):
    """Section 5.0 Record Payment's Bank Account picker (Section 5.4.E) — active
    accounts only, matching Screen 18's Active/Inactive toggle; a deactivated
    bank shouldn't be selectable for a new payment even though old payments
    that reference it are left alone."""
    rows = supabase.table("bank_accounts").select("bank_name").eq("is_active", True).execute().data
    return BankAccountsOut(bank_accounts=sorted(row["bank_name"] for row in rows))
