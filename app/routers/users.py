from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from app.database import get_supabase
from app.dependencies import require_admin
from app.models.user import UserCreate, UserOut
from app.services import activity_log_service, email_service, user_service
from app.services.email_service import EmailDispatchError
from app.services.user_service import (
    CannotDeactivateLastAdminError,
    CannotDeactivateSelfError,
    DuplicateEmailError,
    UserNotFoundError,
)

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.post("", response_model=UserOut, status_code=201)
def create_user_endpoint(
    data: UserCreate, admin: dict = Depends(require_admin), supabase: Client = Depends(get_supabase)
):
    """Screen 12 '+ Add User' — the only way a new account is ever created
    (Section 3: no public signup route exists anywhere)."""
    try:
        user, temp_password = user_service.create_user(supabase, data.full_name, data.email, data.role)
    except DuplicateEmailError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    try:
        email_service.send_temp_password_email(user.email, user.full_name, temp_password)
    except EmailDispatchError:
        pass  # user is created either way; Gmail creds may still be a placeholder

    activity_log_service.log_activity(
        supabase, admin["id"], "user_created", f"Created {data.role} user '{user.full_name}' ({user.email})"
    )
    return user


@router.get("", response_model=list[UserOut])
def list_users_endpoint(admin: dict = Depends(require_admin), supabase: Client = Depends(get_supabase)):
    return user_service.list_users(supabase)


@router.patch("/{user_id}/deactivate", response_model=UserOut)
def deactivate_user_endpoint(
    user_id: str, admin: dict = Depends(require_admin), supabase: Client = Depends(get_supabase)
):
    """Soft-disable login (Section 5.2) — never a delete."""
    try:
        deactivated = user_service.deactivate_user(supabase, user_id, admin["id"])
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (CannotDeactivateSelfError, CannotDeactivateLastAdminError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    activity_log_service.log_activity(
        supabase, admin["id"], "user_deactivated", f"Deactivated user '{deactivated.full_name}' ({deactivated.email})"
    )
    return deactivated
