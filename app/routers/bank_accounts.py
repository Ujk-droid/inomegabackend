from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from app.database import get_supabase
from app.dependencies import require_admin
from app.models.bank_account import BankAccountCreate, BankAccountOut, BankAccountUpdate
from app.services.bank_account_service import (
    BankAccountNotFoundError,
    create_bank_account,
    list_bank_accounts,
    update_bank_account,
)

router = APIRouter(prefix="/api/v1/bank-accounts", tags=["bank-accounts"])


@router.get("", response_model=list[BankAccountOut])
def list_bank_accounts_endpoint(admin: dict = Depends(require_admin), supabase: Client = Depends(get_supabase)):
    """Screen 18 — every bank account (active and inactive), Admin-only. The
    active-only/names-only GET /master-data/bank-accounts stays separate —
    that one's for the Record Payment picker, any authenticated user."""
    return list_bank_accounts(supabase)


@router.post("", response_model=BankAccountOut, status_code=201)
def create_bank_account_endpoint(
    data: BankAccountCreate, admin: dict = Depends(require_admin), supabase: Client = Depends(get_supabase)
):
    return create_bank_account(supabase, data)


@router.patch("/{bank_account_id}", response_model=BankAccountOut)
def update_bank_account_endpoint(
    bank_account_id: str,
    data: BankAccountUpdate,
    admin: dict = Depends(require_admin),
    supabase: Client = Depends(get_supabase),
):
    """Screen 18's Active/Inactive <Switch> per row."""
    try:
        return update_bank_account(supabase, bank_account_id, data)
    except BankAccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
