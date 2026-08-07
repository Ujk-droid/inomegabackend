from fastapi import APIRouter, Depends
from supabase import Client

from app.database import get_supabase
from app.dependencies import require_admin
from app.services.scheduler import send_daily_digest

router = APIRouter(prefix="/api/v1/internal", tags=["internal"])


@router.post("/run-digest")
def run_digest_endpoint(admin: dict = Depends(require_admin), supabase: Client = Depends(get_supabase)):
    """Manual trigger for Section 7.1's daily digest — lets an Admin (or a
    test) fire it on demand instead of waiting for the 8 AM scheduled run."""
    return send_daily_digest(supabase)
