import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from supabase import Client

from app.config import settings
from app.database import get_supabase
from app.dependencies import SESSION_COOKIE_NAME, get_current_user
from app.models.auth import ForgotPasswordCreate, LoginCreate, LoginResponse, ResetPasswordCreate
from app.services import auth_service, email_service, login_gate_service, notification_preferences_service, user_service
from app.services.email_service import EmailDispatchError

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

RESET_TOKEN_EXPIRE_HOURS = 1


def _set_session_cookie(response: Response, user_id: str, role: str) -> None:
    token = auth_service.create_access_token(user_id, role)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=auth_service.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/login", response_model=LoginResponse)
def login(data: LoginCreate, request: Request, response: Response, supabase: Client = Depends(get_supabase)):
    """Section 3/3.1 — Admin logs in directly; Staff always goes through the
    Login Approval Gate, even on a correct password (Section 3.1: 'a Staff
    login is not just correct password = in')."""
    incorrect = HTTPException(status_code=401, detail="Incorrect email or password")

    user = user_service.get_user_by_email(supabase, data.email)
    if user is None:
        raise incorrect
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="This account has been deactivated")
    if auth_service.is_locked(user):
        raise HTTPException(
            status_code=423,
            detail="Account locked after too many failed attempts. Try again in a few minutes.",
        )

    if not auth_service.verify_password(data.password, user["password_hash"]):
        supabase.table("users").update(
            auth_service.record_failed_login(user.get("failed_login_attempts", 0))
        ).eq("id", user["id"]).execute()
        raise incorrect

    supabase.table("users").update(auth_service.record_successful_login()).eq("id", user["id"]).execute()

    if user["role"] == "admin":
        _set_session_cookie(response, user["id"], user["role"])
        return LoginResponse(status="authenticated", role="admin")

    ip_address = request.client.host if request.client else None
    pending = login_gate_service.create_pending_request(supabase, user["id"], ip_address)
    _notify_admins_of_pending_login(supabase, user)
    return LoginResponse(status="pending", request_id=pending["id"])


def _notify_admins_of_pending_login(supabase: Client, staff_user: dict) -> None:
    """Section 3.1: 'Every Admin currently active gets notified immediately ...
    an email alert if not [online].' The live in-session badge/toast half is a
    frontend (Phase 4) concern — there's no UI to show a badge in yet.
    Section 10's login_approval_request preference (default on) can turn this
    off per-admin — checked per recipient, never a global switch."""
    admins = supabase.table("users").select("id, email").eq("role", "admin").eq("is_active", True).execute()
    for admin in admins.data:
        if not notification_preferences_service.get_preferences(supabase, admin["id"]).login_approval_request:
            continue
        try:
            email_service.send_login_request_notification(admin["email"], staff_user["full_name"])
        except EmailDispatchError:
            pass  # best-effort — Gmail creds may still be a placeholder; login must not fail because of this


@router.get("/login-requests/{request_id}/status")
def poll_login_request(request_id: str, response: Response, supabase: Client = Depends(get_supabase)):
    """Screen 1's 'Waiting for admin approval...' polling target. The moment
    this observes 'approved', it sets the session cookie right here — this is
    what makes the waiting screen 'proceed into the app automatically, without
    them re-entering credentials' (Section 3.1) actually true."""
    request_row = login_gate_service.get_request(supabase, request_id)
    if request_row is None:
        raise HTTPException(status_code=404, detail=f"Login request '{request_id}' not found")

    if request_row["status"] == "approved":
        user = user_service.require_user(supabase, request_row["user_id"])
        _set_session_cookie(response, user["id"], user["role"])

    return {"status": request_row["status"]}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"status": "logged_out"}


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return user_service.row_to_out(user)


@router.post("/forgot-password")
def forgot_password(data: ForgotPasswordCreate, supabase: Client = Depends(get_supabase)):
    """Screen 1 — always the same generic response, whether or not the email
    exists (Section 6: 'a basic security practice, not optional')."""
    generic = {"message": "If that email exists, we've sent a reset link"}
    user = user_service.get_user_by_email(supabase, data.email)
    if user is None:
        return generic

    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=RESET_TOKEN_EXPIRE_HOURS)
    supabase.table("users").update(
        {"reset_token": token, "reset_token_expires": expires.isoformat()}
    ).eq("id", user["id"]).execute()

    try:
        email_service.send_password_reset_email(user["email"], token)
    except EmailDispatchError:
        pass  # never reveal success/failure via the response either way
    return generic


@router.post("/reset-password/{token}")
def reset_password(token: str, data: ResetPasswordCreate, supabase: Client = Depends(get_supabase)):
    resp = supabase.table("users").select("*").eq("reset_token", token).limit(1).execute()
    user = resp.data[0] if resp.data else None

    if user is None or not user.get("reset_token_expires"):
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")

    expires_at = auth_service.parse_timestamp(user["reset_token_expires"])
    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")

    supabase.table("users").update(
        {
            "password_hash": auth_service.hash_password(data.new_password),
            "reset_token": None,
            "reset_token_expires": None,
        }
    ).eq("id", user["id"]).execute()
    return {"message": "Password updated"}
