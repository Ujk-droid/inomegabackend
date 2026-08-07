"""Section 7.1's second heartbeat (daily low-stock digest) + Section 5.3's
overdue-status flip (deferred from Phase 2) + Section 3.1's login-request
expiry (block 3B). One BackgroundScheduler, three jobs — guarded by
settings.enable_scheduler so pytest/local dev never fires a real scheduled
job against the real Supabase project by accident (see app/config.py)."""

from datetime import date, datetime, timezone
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from supabase import Client

from app.services import inbox_service, ledger_math, login_gate_service, notification_preferences_service
from app.services.email_service import EmailDispatchError, send_email
from app.services.gmail_client import GmailApiError

TIMEZONE = "Asia/Karachi"
PROGRESS_FILE = Path(__file__).resolve().parent.parent.parent / "progress.md"

_scheduler: BackgroundScheduler | None = None


def _log_spine(message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    try:
        with open(PROGRESS_FILE, "a") as f:
            f.write(f"- [{timestamp}] {message}\n")
    except OSError:
        pass  # logging must never be the reason a scheduled job fails


def flip_overdue_invoices(supabase: Client, today: date | None = None) -> list[dict]:
    """Section 5.3: 'a scheduled daily beat checks every finalized invoice each
    morning and flips unpaid/partial -> overdue where the date has passed.'"""
    today = today or date.today()
    resp = (
        supabase.table("customer_ledgers")
        .select("*")
        .eq("invoice_state", "finalized")
        .eq("txn_type", "sale")
        .is_("deleted_at", "null")
        .execute()
    )

    flipped = []
    for row in resp.data:
        if row["invoice_status"] not in ("unpaid", "partial"):
            continue
        due_date_raw = row.get("due_date")
        if not due_date_raw:
            continue
        due_date = due_date_raw if isinstance(due_date_raw, date) else date.fromisoformat(str(due_date_raw))

        new_status = ledger_math.compute_invoice_status(
            row["total_amount"], row.get("received_at_sale") or 0, due_date, today
        )
        if new_status != row["invoice_status"]:
            supabase.table("customer_ledgers").update({"invoice_status": new_status}).eq("id", row["id"]).execute()
            row["invoice_status"] = new_status
            flipped.append(row)
    return flipped


def _low_stock_items(supabase: Client) -> list[dict]:
    resp = supabase.table("inventory_items").select("*").execute()
    return [row for row in resp.data if row["quantity_in_stock"] <= row["min_threshold"]]


def _overdue_invoices(supabase: Client) -> list[dict]:
    resp = (
        supabase.table("customer_ledgers")
        .select("*")
        .eq("invoice_status", "overdue")
        .is_("deleted_at", "null")
        .execute()
    )
    return resp.data


def _active_admins(supabase: Client) -> list[dict]:
    resp = supabase.table("users").select("id, email").eq("role", "admin").eq("is_active", True).execute()
    return resp.data


def send_daily_digest(supabase: Client) -> dict:
    """Section 7.1: 'a plain schedule, not conditional — it always sends, even
    if the list is empty ... so silence never gets confused with nothing to
    check.' Runs the overdue flip first so the digest reflects fresh statuses
    (Section 5.3: 'includes overdue invoices in the same daily digest')."""
    flip_overdue_invoices(supabase)

    low_stock = _low_stock_items(supabase)
    overdue = _overdue_invoices(supabase)

    lines = ["Omega Scales — Daily Digest", ""]
    if low_stock:
        lines.append(f"Low stock ({len(low_stock)} item(s) at or below threshold):")
        lines += [f"  - {i['item_code']}: {i['quantity_in_stock']} in stock (min {i['min_threshold']})" for i in low_stock]
    else:
        lines.append("Low stock: no items below threshold today.")

    lines.append("")
    if overdue:
        lines.append(f"Overdue invoices ({len(overdue)}):")
        lines += [f"  - Invoice #{i.get('invoice_no')}: Rs. {i['total_amount']} (due {i.get('due_date')})" for i in overdue]
    else:
        lines.append("Overdue invoices: none today.")
    body = "\n".join(lines)

    admins = _active_admins(supabase)
    sent_to = []
    for admin in admins:
        # Section 10's low_stock_digest preference (default on) gates the
        # whole digest per-admin — this is the only toggle in the requested
        # set that covers this email, so it's treated as "do you want the
        # daily digest at all," not split by low-stock vs. overdue.
        if not notification_preferences_service.get_preferences(supabase, admin["id"]).low_stock_digest:
            continue
        try:
            send_email(admin["email"], "Omega Scales — Daily Digest", body)
            sent_to.append(admin["email"])
        except EmailDispatchError:
            pass  # Gmail creds may still be a placeholder — must never crash the scheduled job

    _log_spine(
        f"Daily digest: {len(low_stock)} low-stock item(s), {len(overdue)} overdue invoice(s), "
        f"sent to {len(sent_to)}/{len(admins)} admin(s)."
    )
    return {"low_stock_count": len(low_stock), "overdue_count": len(overdue), "sent_to": sent_to}


def expire_stale_login_requests(supabase: Client) -> list[dict]:
    return login_gate_service.expire_stale_requests(supabase)


def sync_gmail_inbox(supabase: Client) -> dict | None:
    """Section 9.1's poll (no Pub/Sub push — too heavy for 8-10 users). Silent
    no-op while GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN are still .env placeholders,
    same 'never crash the scheduled job' discipline as send_daily_digest."""
    try:
        return inbox_service.sync_inbox(supabase)
    except GmailApiError:
        return None


def start_scheduler(supabase: Client) -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        lambda: send_daily_digest(supabase), CronTrigger(hour=8, minute=0, timezone=TIMEZONE), id="daily_digest"
    )
    scheduler.add_job(
        lambda: expire_stale_login_requests(supabase), IntervalTrigger(minutes=1), id="expire_login_requests"
    )
    scheduler.add_job(lambda: sync_gmail_inbox(supabase), IntervalTrigger(minutes=5), id="sync_gmail_inbox")
    scheduler.start()
    _scheduler = scheduler
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
