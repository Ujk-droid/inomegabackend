from fastapi import APIRouter, Depends
from supabase import Client

from app.database import get_supabase
from app.dependencies import get_current_user
from app.models.notification_preferences import NotificationPreferencesOut, NotificationPreferencesUpdate
from app.services import notification_preferences_service

router = APIRouter(prefix="/api/v1/notification-preferences", tags=["notification-preferences"])


@router.get("", response_model=NotificationPreferencesOut)
def get_preferences_endpoint(
    user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    """Screen 10 Settings — every user (Admin or Staff) manages their own
    notification preferences; there's nothing Admin-only about which alerts
    you personally want to receive."""
    return notification_preferences_service.get_preferences(supabase, user["id"])


@router.patch("", response_model=NotificationPreferencesOut)
def update_preferences_endpoint(
    data: NotificationPreferencesUpdate,
    user: dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    return notification_preferences_service.update_preferences(supabase, user["id"], data)
