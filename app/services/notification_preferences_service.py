"""Screen 10 Settings' Notification preferences (Section 4.3's <Switch>
toggles) — per-user, defaulting to all-on. A row is created lazily on first
read/write rather than at signup, so existing users never need a backfill
migration; get_preferences returns the all-on defaults for a user with no row
yet, exactly as if one existed."""

from supabase import Client

from app.models.notification_preferences import NotificationPreferencesOut, NotificationPreferencesUpdate

_DEFAULTS = {"low_stock_digest": True, "human_gate_approval": True, "login_approval_request": True}


def _row_to_out(row: dict) -> NotificationPreferencesOut:
    return NotificationPreferencesOut(
        low_stock_digest=row.get("low_stock_digest", True),
        human_gate_approval=row.get("human_gate_approval", True),
        login_approval_request=row.get("login_approval_request", True),
    )


def get_preferences(supabase: Client, user_id: str) -> NotificationPreferencesOut:
    resp = supabase.table("notification_preferences").select("*").eq("user_id", user_id).limit(1).execute()
    if resp.data:
        return _row_to_out(resp.data[0])
    return NotificationPreferencesOut(**_DEFAULTS)


def update_preferences(
    supabase: Client, user_id: str, data: NotificationPreferencesUpdate
) -> NotificationPreferencesOut:
    changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}

    existing = supabase.table("notification_preferences").select("*").eq("user_id", user_id).limit(1).execute()
    if existing.data:
        resp = supabase.table("notification_preferences").update(changes).eq("user_id", user_id).execute()
        return _row_to_out(resp.data[0])

    resp = supabase.table("notification_preferences").insert({**_DEFAULTS, **changes, "user_id": user_id}).execute()
    return _row_to_out(resp.data[0])
