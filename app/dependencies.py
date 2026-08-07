"""Section 3 RBAC — get_current_user/require_admin are the two dependencies
every router uses to enforce the Admin/Staff table. No auth existed before
Phase 3; this file is the single place that reads the session cookie."""

from fastapi import Cookie, Depends, HTTPException
from supabase import Client

from app.database import get_supabase
from app.services import auth_service

SESSION_COOKIE_NAME = "omega_session"


def get_current_user(
    omega_session: str | None = Cookie(default=None),
    supabase: Client = Depends(get_supabase),
) -> dict:
    if omega_session is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = auth_service.decode_token(omega_session)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    resp = supabase.table("users").select("*").eq("id", payload["sub"]).limit(1).execute()
    if not resp.data:
        raise HTTPException(status_code=401, detail="User no longer exists")

    user = resp.data[0]
    if not user.get("is_active", True):
        raise HTTPException(status_code=401, detail="Account deactivated")
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
