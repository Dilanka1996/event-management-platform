"""Invitations: idempotent bulk insert + keyset-paginated listing.

Emails are PII: the chokepoint's `view_pii` capability (not the route) decides
whether they are serialised into the response body.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import (
    CurrentUser,
    get_current_user,
    has_capability,
    require_event_capability,
)
from app.db import get_session
from app.schemas import InvitationCreate, InvitationOut, InvitationPage, PreviewResult

router = APIRouter(prefix="/events/{event_id}/invitations", tags=["invitations"])


def _serialize(row, can_view_pii: bool) -> InvitationOut:
    return InvitationOut(
        id=row.id,
        event_id=row.event_id,
        email=row.email if can_view_pii else None,
        status=row.status,
        created_at=row.created_at,
    )


@router.post("", response_model=InvitationPage | PreviewResult, status_code=201)
def create_invitations(
    event_id: int,
    payload: InvitationCreate,
    dry_run: bool = False,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    require_event_capability(db, user, event_id, "invite_attendees")

    if dry_run:
        return PreviewResult(
            would_commit=True,
            action="create_invitations",
            summary=f"Would invite {len(payload.emails)} attendee(s) to event {event_id}",
            details={"emails": payload.emails},
        )

    inserted = 0
    if payload.emails:
        result = db.execute(
            text(
                "INSERT INTO invitations (event_id, email, status) "
                "SELECT :e, unnest(:emails::text[]), 'PENDING' "
                "ON CONFLICT (event_id, email) DO NOTHING "
                "RETURNING id, event_id, email, status, created_at"
            ),
            {"e": event_id, "emails": payload.emails},
        )
        rows = result.all()
        inserted = len(rows)
    else:
        rows = []
    db.commit()

    # The caller just wrote them, so they may see what they wrote (view_pii is
    # true for any role that can invite_attendees per the capability table).
    can_pii = has_capability(db, user, event_id, "view_pii")
    return InvitationPage(
        items=[_serialize(r, can_pii) for r in rows],
        next_cursor=None,
    )


@router.get("", response_model=InvitationPage)
def list_invitations(
    event_id: int,
    cursor: int | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> InvitationPage:
    """Keyset pagination on (event_id, id) — the 50k-scale surface."""
    require_event_capability(db, user, event_id, "read")

    sql = (
        "SELECT id, event_id, email, status, created_at FROM invitations "
        "WHERE event_id = :e"
    )
    params: dict = {"e": event_id, "limit": limit}
    if cursor is not None:
        sql += " AND id > :cursor"
        params["cursor"] = cursor
    sql += " ORDER BY id LIMIT :limit"

    rows = db.execute(text(sql), params).all()
    next_cursor = rows[-1].id if len(rows) == limit else None
    can_pii = has_capability(db, user, event_id, "view_pii")
    return InvitationPage(
        items=[_serialize(r, can_pii) for r in rows],
        next_cursor=next_cursor,
    )
