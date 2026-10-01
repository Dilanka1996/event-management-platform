"""Event roster + role assignment. The roster is gated by `view_roster`,
and every email in the body by `view_pii` — an ATTENDEE gets a 403 here.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import (
    CurrentUser,
    get_current_user,
    has_capability,
    require_event_capability,
)
from app.db import get_session
from app.schemas import MemberAdd, MemberOut, MemberPage

router = APIRouter(prefix="/events/{event_id}/members", tags=["members"])

_VALID_ROLES = {"ADMIN", "CONTRIBUTOR", "ATTENDEE"}


@router.get("", response_model=MemberPage)
def list_members(
    event_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> MemberPage:
    require_event_capability(db, user, event_id, "view_roster")
    can_pii = has_capability(db, user, event_id, "view_pii")

    rows = db.execute(
        text(
            "SELECT u.id AS user_id, u.email, u.name, r.role "
            "FROM event_roles r JOIN users u ON u.id = r.user_id "
            "WHERE r.event_id = :e ORDER BY u.id"
        ),
        {"e": event_id},
    ).all()

    return MemberPage(
        items=[
            MemberOut(
                user_id=r.user_id,
                email=r.email if can_pii else None,
                name=r.name,
                role=r.role,
            )
            for r in rows
        ]
    )


@router.post("", response_model=MemberOut, status_code=201)
def add_member(
    event_id: int,
    payload: MemberAdd,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> MemberOut:
    require_event_capability(db, user, event_id, "manage_members")

    if payload.role not in _VALID_ROLES:
        raise HTTPException(status_code=422, detail=f"Invalid role: {payload.role}")

    target = db.execute(
        text("SELECT id, email, name FROM users WHERE email = :e"),
        {"e": payload.email},
    ).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    db.execute(
        text(
            "INSERT INTO event_roles (user_id, event_id, role) "
            "VALUES (:u, :e, :r) "
            "ON CONFLICT (user_id, event_id) DO UPDATE SET role = EXCLUDED.role"
        ),
        {"u": target.id, "e": event_id, "r": payload.role},
    )
    db.commit()

    can_pii = has_capability(db, user, event_id, "view_pii")
    return MemberOut(
        user_id=target.id,
        email=target.email if can_pii else None,
        name=target.name,
        role=payload.role,
    )
