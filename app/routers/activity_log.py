from datetime import date

from fastapi import APIRouter, Depends, Query
from supabase import Client

from app.database import get_supabase
from app.dependencies import require_admin
from app.models.activity_log import ActivityLogOut
from app.services.activity_log_service import list_activity

router = APIRouter(prefix="/api/v1/activity-log", tags=["activity-log"])


@router.get("", response_model=list[ActivityLogOut])
def list_activity_log_endpoint(
    action: str | None = Query(None),
    search: str | None = Query(None, description="Matches target_description"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    admin: dict = Depends(require_admin),
    supabase: Client = Depends(get_supabase),
):
    """Screen (Section 16.4) — Admin only, read-only. No POST/PATCH/DELETE
    here on purpose: entries are written by the sensitive actions themselves
    (via activity_log_service.log_activity), never through this router."""
    return list_activity(supabase, action=action, search=search, start_date=start_date, end_date=end_date)
