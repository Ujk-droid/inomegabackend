"""Section 16.4 — Activity Log. Append-only: written to by every sensitive
write already happening elsewhere (rate changes, deactivations, correction
entries, credit-limit overrides, stock adjustments, sales returns, payment
corrections) — never read from by those callers, and never updated/deleted
by anyone, Admin included. That last part is deliberate (Section 16.4: "an
audit log that could be erased isn't an audit log") — this module exposes no
delete/update function at all, not even an Admin-gated one."""

from datetime import date

from supabase import Client

from app.models.activity_log import ActivityLogOut


def log_activity(supabase: Client, user_id: str, action: str, target_description: str) -> None:
    supabase.table("activity_log").insert(
        {"user_id": user_id, "action": action, "target_description": target_description}
    ).execute()


def _user_names(supabase: Client) -> dict[str, str]:
    return {row["id"]: row["full_name"] for row in supabase.table("users").select("id, full_name").execute().data}


def list_activity(
    supabase: Client,
    *,
    action: str | None = None,
    search: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[ActivityLogOut]:
    query = supabase.table("activity_log").select("*")
    if action:
        query = query.eq("action", action)
    if search:
        query = query.ilike("target_description", f"%{search}%")
    if start_date:
        query = query.gte("created_at", start_date.isoformat())
    if end_date:
        query = query.lte("created_at", f"{end_date.isoformat()}T23:59:59")

    resp = query.order("created_at", desc=True).execute()
    user_names = _user_names(supabase)
    return [
        ActivityLogOut(
            id=row["id"],
            user_id=row["user_id"],
            user_name=user_names.get(row["user_id"]),
            action=row["action"],
            target_description=row["target_description"],
            created_at=row.get("created_at"),
        )
        for row in resp.data
    ]
