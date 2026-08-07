from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import Client

from app.database import get_supabase
from app.dependencies import get_current_user, require_admin
from app.models.inbox import GenerateReplyOut, InboxMessageOut, MarkReadUpdate, ReplyCreate, SyncResult
from app.services import inbox_service
from app.services.gmail_client import GmailApiError
from app.services.inbox_service import InboxMessageNotFoundError

router = APIRouter(prefix="/api/v1/inbox", tags=["inbox"])


@router.post("/sync", response_model=SyncResult)
def sync_inbox_endpoint(admin: dict = Depends(require_admin), supabase: Client = Depends(get_supabase)):
    """Manual trigger for the scheduler's 5-minute Gmail poll (Section 9.1) —
    Admin-only, same pattern as /internal/run-digest."""
    try:
        return inbox_service.sync_inbox(supabase)
    except GmailApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("", response_model=list[InboxMessageOut])
def list_inbox_endpoint(
    is_read: bool | None = Query(None),
    user: dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Section 9.1: 'both Admin and Staff can read and reply.'"""
    return [inbox_service.row_to_out(row) for row in inbox_service.list_messages(supabase, is_read)]


@router.get("/{message_id}", response_model=InboxMessageOut)
def get_inbox_message_endpoint(
    message_id: str, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    try:
        return inbox_service.row_to_out(inbox_service.get_message(supabase, message_id))
    except InboxMessageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{message_id}", response_model=InboxMessageOut)
def mark_read_endpoint(
    message_id: str,
    data: MarkReadUpdate,
    user: dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    try:
        return inbox_service.row_to_out(inbox_service.set_read_state(supabase, message_id, data.is_read))
    except InboxMessageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{message_id}", status_code=204)
def delete_inbox_message_endpoint(
    message_id: str, admin: dict = Depends(require_admin), supabase: Client = Depends(get_supabase)
):
    """Section 9.1: 'only Admin can delete.'"""
    try:
        inbox_service.delete_message(supabase, message_id)
    except InboxMessageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{message_id}/reply")
def reply_to_message_endpoint(
    message_id: str,
    data: ReplyCreate,
    user: dict = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    try:
        inbox_service.reply_to_message(supabase, message_id, data.body, data.attach_invoice_no)
    except InboxMessageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GmailApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"status": "sent"}


@router.post("/{message_id}/generate-reply", response_model=GenerateReplyOut)
def generate_reply_endpoint(
    message_id: str, user: dict = Depends(get_current_user), supabase: Client = Depends(get_supabase)
):
    """Section 9.1: 'it is a draft, never auto-sent' — Admin/Staff reviews and
    edits before pressing Send separately via /reply above."""
    try:
        draft = inbox_service.generate_ai_reply(supabase, message_id)
    except InboxMessageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return GenerateReplyOut(draft=draft)
