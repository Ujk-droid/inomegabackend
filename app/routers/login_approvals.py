from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import Client

from app.database import get_supabase
from app.dependencies import require_admin
from app.models.auth import LoginRequestNote, LoginRequestOut
from app.services import login_gate_service
from app.services.login_gate_service import LoginRequestAlreadyResolvedError, LoginRequestNotFoundError

router = APIRouter(prefix="/api/v1/login-requests", tags=["login-approvals"])


def _row_to_out(row: dict) -> LoginRequestOut:
    return LoginRequestOut(
        id=row["id"],
        user_id=row["user_id"],
        status=row["status"],
        requested_at=row.get("requested_at"),
        resolved_at=row.get("resolved_at"),
        resolved_by=row.get("resolved_by"),
        ip_address=row.get("ip_address"),
        note=row.get("note"),
    )


@router.get("", response_model=list[LoginRequestOut])
def list_login_requests(
    status: str | None = Query(None, description="'pending' | 'approved' | 'rejected' | 'expired'"),
    admin: dict = Depends(require_admin),
    supabase: Client = Depends(get_supabase),
):
    """Screen 14 — Login Approvals: pending queue at the top, full searchable
    history below it. Admin-only, matching the Route Map (Section 3.2)."""
    return [_row_to_out(row) for row in login_gate_service.list_requests(supabase, status)]


@router.post("/{request_id}/approve", response_model=LoginRequestOut)
def approve_login_request(
    request_id: str, admin: dict = Depends(require_admin), supabase: Client = Depends(get_supabase)
):
    try:
        return _row_to_out(login_gate_service.approve_request(supabase, request_id, admin["id"]))
    except LoginRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LoginRequestAlreadyResolvedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{request_id}/reject", response_model=LoginRequestOut)
def reject_login_request(
    request_id: str, admin: dict = Depends(require_admin), supabase: Client = Depends(get_supabase)
):
    try:
        return _row_to_out(login_gate_service.reject_request(supabase, request_id, admin["id"]))
    except LoginRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LoginRequestAlreadyResolvedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/{request_id}/note", response_model=LoginRequestOut)
def annotate_login_request(
    request_id: str,
    data: LoginRequestNote,
    admin: dict = Depends(require_admin),
    supabase: Client = Depends(get_supabase),
):
    try:
        return _row_to_out(login_gate_service.add_note(supabase, request_id, data.note))
    except LoginRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{request_id}", status_code=204)
def delete_login_request(
    request_id: str, admin: dict = Depends(require_admin), supabase: Client = Depends(get_supabase)
):
    """Soft delete (Section 5.2) — an Admin can remove old entries from the
    visible history without destroying the audit trail."""
    try:
        login_gate_service.soft_delete_request(supabase, request_id)
    except LoginRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
