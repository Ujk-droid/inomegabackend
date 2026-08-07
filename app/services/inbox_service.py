"""Section 9.1 — Gmail Inbox: sync (matching), list/read/reply/mark/delete.
Only messages matched to a known party or a recognized invoice number are
kept — this is a filtered view, never the Admin's whole personal inbox."""

import re
from email.utils import parseaddr, parsedate_to_datetime

from supabase import Client

from app.models.inbox import InboxMessageOut
from app.services import gmail_client, party_service
from app.services.ledger_service import fetch_invoice_by_number

INVOICE_SUBJECT_PATTERN = re.compile(r"invoice\s*#\s*(\d+)", re.IGNORECASE)

SYNC_QUERY = "in:inbox"
SYNC_MAX_RESULTS = 50


class InboxMessageNotFoundError(Exception):
    pass


def _extract_invoice_no(subject: str) -> str | None:
    match = INVOICE_SUBJECT_PATTERN.search(subject or "")
    return match.group(1) if match else None


def _already_synced(supabase: Client, gmail_message_id: str) -> bool:
    resp = (
        supabase.table("inbox_messages")
        .select("id")
        .eq("gmail_message_id", gmail_message_id)
        .limit(1)
        .execute()
    )
    return bool(resp.data)


def sync_inbox(supabase: Client) -> dict:
    """Polled by the scheduler (every 5 minutes) and by the manual /inbox/sync
    endpoint. Fetches recent Gmail messages and keeps only the ones matched to
    a known party email or a recognized invoice number (Section 9.1)."""
    message_ids = gmail_client.list_message_ids(SYNC_QUERY, max_results=SYNC_MAX_RESULTS)

    synced = 0
    skipped_unmatched = 0
    already_seen = 0

    for message_id in message_ids:
        if _already_synced(supabase, message_id):
            already_seen += 1
            continue

        detail = gmail_client.get_message(message_id)
        _name, from_email = parseaddr(detail["from_email"])

        party = party_service.find_party_by_email(supabase, from_email) if from_email else None
        invoice_no = _extract_invoice_no(detail["subject"])
        invoice = fetch_invoice_by_number(supabase, invoice_no) if invoice_no else None

        if party is None and invoice is None:
            skipped_unmatched += 1
            continue

        received_at = _parse_received_at(detail.get("received_at_header"))
        payload = {
            "gmail_message_id": detail["gmail_message_id"],
            "gmail_thread_id": detail["gmail_thread_id"],
            "from_email": from_email or detail["from_email"],
            "party_id": party["id"] if party else None,
            "related_invoice_no": invoice["invoice_no"] if invoice else None,
            "subject": detail["subject"],
            "snippet": detail["snippet"],
            "received_at": received_at,
            "is_read": False,
            "is_deleted": False,
        }
        supabase.table("inbox_messages").insert(payload).execute()
        synced += 1

    return {"synced": synced, "already_seen": already_seen, "skipped_unmatched": skipped_unmatched}


def _parse_received_at(header_value: str | None) -> str:
    from datetime import datetime, timezone

    if header_value:
        try:
            return parsedate_to_datetime(header_value).isoformat()
        except (TypeError, ValueError):
            pass
    return datetime.now(timezone.utc).isoformat()


def row_to_out(row: dict) -> InboxMessageOut:
    return InboxMessageOut(
        id=row["id"],
        gmail_thread_id=row["gmail_thread_id"],
        from_email=row["from_email"],
        party_id=row.get("party_id"),
        related_invoice_no=row.get("related_invoice_no"),
        subject=row.get("subject"),
        snippet=row.get("snippet"),
        received_at=row["received_at"],
        is_read=row.get("is_read", False),
        is_deleted=row.get("is_deleted", False),
    )


def list_messages(supabase: Client, is_read: bool | None = None) -> list[dict]:
    query = supabase.table("inbox_messages").select("*").eq("is_deleted", False)
    if is_read is not None:
        query = query.eq("is_read", is_read)
    resp = query.order("received_at", desc=True).execute()
    return resp.data


def get_message(supabase: Client, message_id: str) -> dict:
    resp = supabase.table("inbox_messages").select("*").eq("id", message_id).limit(1).execute()
    if not resp.data:
        raise InboxMessageNotFoundError(f"Inbox message '{message_id}' not found")
    return resp.data[0]


def set_read_state(supabase: Client, message_id: str, is_read: bool) -> dict:
    get_message(supabase, message_id)  # 404s if missing
    resp = supabase.table("inbox_messages").update({"is_read": is_read}).eq("id", message_id).execute()
    return resp.data[0]


def delete_message(supabase: Client, message_id: str) -> dict:
    """Section 9.1: 'removes it from the Inbox view (Gmail-side, moves to
    Trash via the API — not permanently destroyed).'"""
    message = get_message(supabase, message_id)
    try:
        gmail_client.trash_message(message["gmail_message_id"])
    except gmail_client.GmailApiError:
        pass  # local soft-delete still proceeds even if Gmail creds are still a placeholder
    resp = supabase.table("inbox_messages").update({"is_deleted": True}).eq("id", message_id).execute()
    return resp.data[0]


def reply_to_message(supabase: Client, message_id: str, body: str, attach_invoice_no: str | None = None) -> None:
    message = get_message(supabase, message_id)

    full_body = body
    if attach_invoice_no:
        invoice = fetch_invoice_by_number(supabase, attach_invoice_no)
        if invoice and invoice.get("pdf_cloudinary_url"):
            full_body = f"{body}\n\nInvoice #{attach_invoice_no}: {invoice['pdf_cloudinary_url']}"

    subject = message["subject"] or ""
    reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    gmail_client.send_message(message["from_email"], reply_subject, full_body, thread_id=message["gmail_thread_id"])


def generate_ai_reply(supabase: Client, message_id: str) -> str:
    """Section 9.1: 'it is a draft, never auto-sent.' Returns the draft text —
    the caller/router never sends it on this message's behalf."""
    from app.services import ai_reply_service

    message = get_message(supabase, message_id)
    invoice = fetch_invoice_by_number(supabase, message["related_invoice_no"]) if message.get("related_invoice_no") else None
    return ai_reply_service.generate_reply_draft(message, invoice)
