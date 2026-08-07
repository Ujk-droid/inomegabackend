from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from app.database import get_supabase
from app.dependencies import get_current_user
from app.models.delivery_challan import DeliveryChallanMarkDelivered, DeliveryChallanOut
from app.services.delivery_challan_service import ChallanNotFoundError, mark_delivered

router = APIRouter(prefix="/api/v1/delivery-challans", tags=["delivery-challans"])


@router.post("/{challan_id}/mark-delivered", response_model=DeliveryChallanOut)
def mark_delivered_endpoint(
    challan_id: str,
    data: DeliveryChallanMarkDelivered,
    user: dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Section 16.5 — marks a Delivery Challan with the date it was actually delivered."""
    try:
        return mark_delivered(supabase, challan_id, data.delivered_at, user["id"])
    except ChallanNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
