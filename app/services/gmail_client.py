"""Section 9.1 — Gmail Inbox reading/replying via the Gmail API (OAuth), a
different capability from Section 9.2's SMTP-only sending. GMAIL_CLIENT_ID/
SECRET/REFRESH_TOKEN are still .env placeholders as of this build (the user's
own decision: build the code now against mocks, wire real credentials later
and do one live smoke test) — every function here raises GmailApiError until
they're supplied.
"""

import base64
from email.mime.text import MIMEText

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import settings

GMAIL_TOKEN_URI = "https://oauth2.googleapis.com/token"
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


class GmailApiError(Exception):
    """Raised for a missing/placeholder OAuth credential, or a failed Gmail API call."""


def _get_service():
    if not (settings.gmail_client_id and settings.gmail_client_secret and settings.gmail_refresh_token):
        raise GmailApiError("Gmail OAuth credentials (GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN) not configured yet")

    creds = Credentials(
        token=None,
        refresh_token=settings.gmail_refresh_token,
        token_uri=GMAIL_TOKEN_URI,
        client_id=settings.gmail_client_id,
        client_secret=settings.gmail_client_secret,
        scopes=GMAIL_SCOPES,
    )
    try:
        return build("gmail", "v1", credentials=creds, cache_discovery=False)
    except HttpError as exc:
        raise GmailApiError(str(exc)) from exc


def _header(headers: list[dict], name: str) -> str | None:
    for header in headers:
        if header["name"].lower() == name.lower():
            return header["value"]
    return None


def list_message_ids(query: str, max_results: int = 25) -> list[str]:
    service = _get_service()
    try:
        resp = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    except HttpError as exc:
        raise GmailApiError(str(exc)) from exc
    return [m["id"] for m in resp.get("messages", [])]


def get_message(message_id: str) -> dict:
    """Returns a parsed dict: gmail_message_id, gmail_thread_id, from_email,
    subject, snippet, received_at (RFC2822 date header, unparsed — caller
    decides how to store it)."""
    service = _get_service()
    try:
        msg = service.users().messages().get(userId="me", id=message_id, format="metadata").execute()
    except HttpError as exc:
        raise GmailApiError(str(exc)) from exc

    headers = msg["payload"]["headers"]
    return {
        "gmail_message_id": msg["id"],
        "gmail_thread_id": msg["threadId"],
        "from_email": _header(headers, "From") or "",
        "subject": _header(headers, "Subject") or "",
        "snippet": msg.get("snippet", ""),
        "received_at_header": _header(headers, "Date"),
    }


def send_message(to_email: str, subject: str, body: str, thread_id: str | None = None) -> str:
    service = _get_service()
    message = MIMEText(body)
    message["to"] = to_email
    message["from"] = settings.gmail_user
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    payload = {"raw": raw}
    if thread_id:
        payload["threadId"] = thread_id

    try:
        sent = service.users().messages().send(userId="me", body=payload).execute()
    except HttpError as exc:
        raise GmailApiError(str(exc)) from exc
    return sent["id"]


def get_full_message(message_id: str) -> dict:
    """Same as get_message but format='full' — includes the MIME payload tree
    (parts, attachment part IDs), needed to verify/read an attachment instead
    of just headers/snippet. Used by the Section 9.2 live send-verification
    check (an outgoing SMTP send fetched back via this read-side API)."""
    service = _get_service()
    try:
        return service.users().messages().get(userId="me", id=message_id, format="full").execute()
    except HttpError as exc:
        raise GmailApiError(str(exc)) from exc


def get_attachment_bytes(message_id: str, attachment_id: str) -> bytes:
    service = _get_service()
    try:
        att = (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )
    except HttpError as exc:
        raise GmailApiError(str(exc)) from exc
    return base64.urlsafe_b64decode(att["data"])


def trash_message(message_id: str) -> None:
    """Section 9.1 Delete: 'moves to Trash via the API — not permanently
    destroyed, matching the retention philosophy of Section 5.2.'"""
    service = _get_service()
    try:
        service.users().messages().trash(userId="me", id=message_id).execute()
    except HttpError as exc:
        raise GmailApiError(str(exc)) from exc
