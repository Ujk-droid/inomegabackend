from datetime import datetime

from pydantic import BaseModel, Field


class InboxMessageOut(BaseModel):
    id: str
    gmail_thread_id: str
    from_email: str
    party_id: str | None = None
    related_invoice_no: str | None = None
    subject: str | None = None
    snippet: str | None = None
    received_at: datetime
    is_read: bool
    is_deleted: bool


class MarkReadUpdate(BaseModel):
    is_read: bool


class ReplyCreate(BaseModel):
    body: str = Field(..., min_length=1)
    attach_invoice_no: str | None = None


class GenerateReplyOut(BaseModel):
    draft: str


class SyncResult(BaseModel):
    synced: int
    already_seen: int
    skipped_unmatched: int
