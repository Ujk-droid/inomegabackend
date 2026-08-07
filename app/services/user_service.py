"""Section 3 / Screen 12 — User Management. There is no public signup route
anywhere: the only way a user row is created is an authenticated Admin calling
create_user below."""

import secrets

from supabase import Client

from app.models.user import UserOut
from app.services import auth_service


class DuplicateEmailError(Exception):
    pass


class UserNotFoundError(Exception):
    pass


class CannotDeactivateSelfError(Exception):
    pass


class CannotDeactivateLastAdminError(Exception):
    pass


def row_to_out(row: dict) -> UserOut:
    return UserOut(
        id=row["id"],
        full_name=row["full_name"],
        email=row["email"],
        role=row["role"],
        is_active=row.get("is_active", True),
        last_login=row.get("last_login"),
        created_at=row.get("created_at"),
    )


def get_user(supabase: Client, user_id: str) -> dict | None:
    resp = supabase.table("users").select("*").eq("id", user_id).limit(1).execute()
    return resp.data[0] if resp.data else None


def require_user(supabase: Client, user_id: str) -> dict:
    user = get_user(supabase, user_id)
    if user is None:
        raise UserNotFoundError(f"User '{user_id}' not found")
    return user


def get_user_by_email(supabase: Client, email: str) -> dict | None:
    resp = supabase.table("users").select("*").eq("email", email).limit(1).execute()
    return resp.data[0] if resp.data else None


def generate_temp_password() -> str:
    return secrets.token_urlsafe(9)


def create_user(supabase: Client, full_name: str, email: str, role: str) -> tuple[UserOut, str]:
    """Returns (created user, temp password) — the router emails the temp
    password and never returns it in the API response body."""
    if get_user_by_email(supabase, email) is not None:
        raise DuplicateEmailError(f"A user with email '{email}' already exists")

    temp_password = generate_temp_password()
    payload = {
        "full_name": full_name,
        "email": email,
        "role": role,
        "password_hash": auth_service.hash_password(temp_password),
    }
    resp = supabase.table("users").insert(payload).execute()
    return row_to_out(resp.data[0]), temp_password


def list_users(supabase: Client) -> list[UserOut]:
    resp = supabase.table("users").select("*").order("full_name", desc=False).execute()
    return [row_to_out(row) for row in resp.data]


def deactivate_user(supabase: Client, user_id: str, acting_admin_id: str) -> UserOut:
    """Soft-disable login (Section 5.2's retention philosophy) — never deletes
    the row, so historical actions stay attributed to a real user.

    Two server-side lockout guards, since there is no reactivate endpoint
    anywhere in this system (deactivation is currently a one-way door):
    an Admin can never deactivate their own account (an Admin cannot approve
    their own unlock afterward, same self-approval impossibility Section 3.1
    already relies on for the Login Approval Gate), and the last remaining
    active Admin can never be deactivated by anyone (there would be no Admin
    left to ever create/reactivate another account)."""
    target = require_user(supabase, user_id)

    if user_id == acting_admin_id:
        raise CannotDeactivateSelfError("You cannot deactivate your own account")

    if target["role"] == "admin" and target.get("is_active", True):
        other_active_admins = (
            supabase.table("users")
            .select("id")
            .eq("role", "admin")
            .eq("is_active", True)
            .neq("id", user_id)
            .execute()
        )
        if not other_active_admins.data:
            raise CannotDeactivateLastAdminError("Cannot deactivate the last active Admin account")

    resp = supabase.table("users").update({"is_active": False}).eq("id", user_id).execute()
    return row_to_out(resp.data[0])
