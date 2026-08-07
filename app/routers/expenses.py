from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import Client

from app.database import get_supabase
from app.dependencies import get_current_user
from app.models.expense import ExpenseCreate, ExpenseOut
from app.services.expense_service import create_expense, list_expenses
from app.services.master_data import UnknownReferenceError
from app.services.party_service import PartyNotFoundError

router = APIRouter(prefix="/api/v1/expenses", tags=["expenses"])


@router.post("", response_model=ExpenseOut, status_code=201)
def create_expense_endpoint(
    data: ExpenseCreate, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    try:
        return create_expense(supabase, data)
    except PartyNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UnknownReferenceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[ExpenseOut])
def list_expenses_endpoint(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    user: dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    return list_expenses(supabase, start_date, end_date)
