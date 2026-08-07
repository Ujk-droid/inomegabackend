"""Section 3.1 — Login Approval Gate. A Staff login doesn't grant access on a
correct password alone; it creates a login_requests row that an Admin must
Approve/Reject, or which auto-expires after 10 minutes unanswered."""

from datetime import datetime, timedelta, timezone

from supabase import Client

EXPIRY_MINUTES = 10


class LoginRequestNotFoundError(Exception):
    pass


class LoginRequestAlreadyResolvedError(Exception):
    """Raised on /approve or /reject when the other Admin already acted first —
    Section 3.1: 'whichever Admin acts first resolves it; the other sees it
    move out of their pending queue too, so two Admins never approve/reject
    the same request twice.'"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_request(supabase: Client, request_id: str) -> dict | None:
    resp = supabase.table("login_requests").select("*").eq("id", request_id).limit(1).execute()
    return resp.data[0] if resp.data else None


def require_request(supabase: Client, request_id: str) -> dict:
    request = get_request(supabase, request_id)
    if request is None:
        raise LoginRequestNotFoundError(f"Login request '{request_id}' not found")
    return request


def create_pending_request(supabase: Client, user_id: str, ip_address: str | None = None) -> dict:
    """Reuses an existing pending request for this user instead of spawning a
    new one on every retried login submit, so an Admin's queue doesn't fill
    with duplicates for one person mashing 'Sign In'."""
    existing = (
        supabase.table("login_requests")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "pending")
        .is_("deleted_at", "null")
        .limit(1)
        .execute()
    )
    if existing.data:
        return existing.data[0]

    payload = {"user_id": user_id, "status": "pending", "ip_address": ip_address}
    resp = supabase.table("login_requests").insert(payload).execute()
    return resp.data[0]


def _resolve(supabase: Client, request_id: str, admin_id: str, new_status: str) -> dict:
    resp = (
        supabase.table("login_requests")
        .update({"status": new_status, "resolved_at": _now_iso(), "resolved_by": admin_id})
        .eq("id", request_id)
        .eq("status", "pending")
        .execute()
    )
    if resp.data:
        return resp.data[0]

    # Nothing matched: either it never existed, or someone else already resolved it.
    existing = get_request(supabase, request_id)
    if existing is None:
        raise LoginRequestNotFoundError(f"Login request '{request_id}' not found")
    raise LoginRequestAlreadyResolvedError(
        f"Login request '{request_id}' was already {existing['status']}"
    )


def approve_request(supabase: Client, request_id: str, admin_id: str) -> dict:
    return _resolve(supabase, request_id, admin_id, "approved")


def reject_request(supabase: Client, request_id: str, admin_id: str) -> dict:
    return _resolve(supabase, request_id, admin_id, "rejected")


def expire_stale_requests(supabase: Client) -> list[dict]:
    """Section 3.1 timeout rule — called by the scheduler (block 3E), every
    minute: any request still 'pending' after EXPIRY_MINUTES flips to 'expired'
    with no Admin action needed."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=EXPIRY_MINUTES)).isoformat()
    resp = (
        supabase.table("login_requests")
        .update({"status": "expired", "resolved_at": _now_iso()})
        .eq("status", "pending")
        .lte("requested_at", cutoff)
        .execute()
    )
    return resp.data


def list_requests(supabase: Client, status: str | None = None) -> list[dict]:
    query = supabase.table("login_requests").select("*").is_("deleted_at", "null")
    if status:
        query = query.eq("status", status)
    resp = query.order("requested_at", desc=True).execute()
    return resp.data


def soft_delete_request(supabase: Client, request_id: str) -> dict:
    require_request(supabase, request_id)
    resp = (
        supabase.table("login_requests")
        .update({"deleted_at": _now_iso()})
        .eq("id", request_id)
        .execute()
    )
    return resp.data[0]


def add_note(supabase: Client, request_id: str, note: str) -> dict:
    require_request(supabase, request_id)
    resp = supabase.table("login_requests").update({"note": note}).eq("id", request_id).execute()
    return resp.data[0]
