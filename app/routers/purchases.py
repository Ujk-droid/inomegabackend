from fastapi import APIRouter, Depends, HTTPException, Response
from supabase import Client

from app.database import get_supabase
from app.dependencies import get_current_user
from app.models.purchase import PurchaseCreate, PurchaseOut
from app.services.inventory_service import ItemNotFoundError
from app.services.ledger_hooks import LedgerIntegrityError
from app.services.party_service import PartyNotFoundError
from app.services.purchase_dispatch_service import build_purchase_pdf_for, build_purchase_preview_pdf
from app.services.purchase_service import (
    create_purchase,
    fetch_purchase,
    list_party_purchases,
    list_purchases,
    row_to_out,
)

router = APIRouter(prefix="/api/v1/purchases", tags=["purchases"])


@router.post("", response_model=PurchaseOut, status_code=201)
def create_purchase_endpoint(
    data: PurchaseCreate, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    try:
        return create_purchase(supabase, data)
    except PartyNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LedgerIntegrityError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/preview-pdf")
def preview_purchase_pdf_endpoint(
    data: PurchaseCreate, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    """Section 9.2's 'live PDF preview', mirrored for Purchase Builder — called
    as items are added, before the purchase is saved. Nothing is persisted."""
    try:
        pdf_bytes = build_purchase_preview_pdf(supabase, data)
    except PartyNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(content=pdf_bytes, media_type="application/pdf")


@router.get("/{purchase_id}/pdf")
def get_purchase_pdf_endpoint(
    purchase_id: str, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    """The real, saved purchase's PDF (actual purchase_bill_no) — used by
    'Print & Save' right after create, so the printed bill isn't the preview's
    'DRAFT' placeholder."""
    row = fetch_purchase(supabase, purchase_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Purchase '{purchase_id}' not found")
    pdf_bytes = build_purchase_pdf_for(supabase, row)
    return Response(content=pdf_bytes, media_type="application/pdf")


@router.get("/{purchase_id}", response_model=PurchaseOut)
def get_purchase_endpoint(
    purchase_id: str, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    row = fetch_purchase(supabase, purchase_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Purchase '{purchase_id}' not found")
    return row_to_out(supabase, row)


@router.get("", response_model=list[PurchaseOut])
def list_purchases_endpoint(
    party_id: str | None = None, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    """Screen 15's list view (Section 5.4.B) when party_id is omitted — every
    purchase across all suppliers, same pattern as GET /invoices. Filtered to
    one supplier when party_id is given (the Party Detail page's usage)."""
    if party_id is not None:
        return list_party_purchases(supabase, party_id)
    return list_purchases(supabase)
