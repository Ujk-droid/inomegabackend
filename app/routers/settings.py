from fastapi import APIRouter, Depends
from supabase import Client

from app.database import get_supabase
from app.dependencies import get_current_user, require_admin
from app.models.settings import SettingsOut, SettingsUpdate
from app.services import settings_service

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
def get_settings_endpoint(user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)):
    """Section 3.2 Settings route: 'reduced view for Staff — no Human Gate
    threshold field.' Same endpoint for both roles; the field is simply null
    for Staff rather than a second response shape."""
    row = settings_service.get_settings_row(supabase)
    is_admin = user["role"] == "admin"
    return SettingsOut(
        human_gate_threshold=float(row["human_gate_threshold"]) if is_admin else None,
        updated_at=row.get("updated_at"),
    )


@router.patch("", response_model=SettingsOut)
def update_settings_endpoint(
    data: SettingsUpdate, admin: dict = Depends(require_admin), supabase: Client = Depends(get_supabase)
):
    """Section 12.1: Admin-editable, and it 'actually changes gate behavior
    when saved' — ledger_service.finalize_invoice reads this same row live."""
    row = settings_service.update_human_gate_threshold(supabase, data.human_gate_threshold, admin["id"])
    return SettingsOut(human_gate_threshold=float(row["human_gate_threshold"]), updated_at=row.get("updated_at"))
