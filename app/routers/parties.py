from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from app.database import get_supabase
from app.dependencies import get_current_user, require_admin
from app.models.ledger import InvoiceOut
from app.models.party import NegotiatedRateCreate, NegotiatedRateOut, PartyBalanceOut, PartyCreate, PartyOut
from app.services.inventory_service import ItemNotFoundError
from app.services.ledger_service import list_party_ledger
from app.services.party_service import (
    DuplicatePartyNameError,
    PartyNotFoundError,
    create_party,
    get_negotiated_rate,
    get_party,
    get_party_balance,
    list_parties,
    row_to_out,
    set_negotiated_rate,
)

router = APIRouter(prefix="/api/v1/parties", tags=["parties"])


@router.post("", response_model=PartyOut, status_code=201)
def create_party_endpoint(
    party: PartyCreate, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    """Minimal Parties CRUD (Screen 11 is a full Phase 4 build) — just enough to
    let Invoice/Purchase/Expense creation reference a real party_id via the API,
    matching Section 5's note that the same customer name must never accidentally
    create two separate ledgers."""
    try:
        return create_party(supabase, party)
    except DuplicatePartyNameError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("", response_model=list[PartyOut])
def list_parties_endpoint(user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)):
    return list_parties(supabase)


@router.get("/{party_id}", response_model=PartyOut)
def get_party_endpoint(
    party_id: str, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    row = get_party(supabase, party_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Party '{party_id}' not found")
    return row_to_out(row)


@router.get("/{party_id}/balance", response_model=PartyBalanceOut)
def get_party_balance_endpoint(
    party_id: str, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    """Section 5.4.A — Current Balance / CR Limit, live, the moment a party is selected."""
    try:
        return get_party_balance(supabase, party_id)
    except PartyNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{party_id}/ledger", response_model=list[InvoiceOut])
def get_party_ledger_endpoint(
    party_id: str, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    """Section 5.2 — default sorted transaction_date/append order, newest first."""
    row = get_party(supabase, party_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Party '{party_id}' not found")
    return list_party_ledger(supabase, party_id)


@router.get("/{party_id}/negotiated-rates/{item_code}", response_model=NegotiatedRateOut)
def get_negotiated_rate_endpoint(
    party_id: str,
    item_code: str,
    user: dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Section 5.4.J 'Low Price' — Invoice Builder reads this the moment a
    party+item pair is selected, to offer their actual negotiated rate
    alongside the flat 10%-off option. A null negotiated_rate is the normal
    case (most party/item pairs have no negotiated rate), not a 404."""
    return get_negotiated_rate(supabase, party_id, item_code)


@router.post("/{party_id}/negotiated-rates", response_model=NegotiatedRateOut, status_code=201)
def set_negotiated_rate_endpoint(
    party_id: str,
    data: NegotiatedRateCreate,
    admin: dict = Depends(require_admin),
    supabase: Client = Depends(get_supabase),
):
    """Admin-only (pricing policy, same tier as the Human Gate threshold and
    Bank Accounts) — upserts, so setting a rate again just updates it."""
    try:
        return set_negotiated_rate(supabase, party_id, data.item_code, data.negotiated_rate)
    except PartyNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
