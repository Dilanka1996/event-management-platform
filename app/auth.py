"""Bearer-token authentication + per-event authorization chokepoint.

The agent talks to the platform only through these dependencies, as the
user's own token — there is no elevated key. Every authorization decision
reads `event_roles` (data-driven), never a handler-level conditional.
"""

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_session

# Role capabilities, driven by data rather than conditionals in handlers.
# "adding a role shouldn't mean editing handlers" → extend this table only.
ROLE_CAPABILITIES: dict[str, set[str]] = {
    "ADMIN": {"read", "write_session", "manage_members", "manage_roles"},
    "CONTRIBUTOR": {"read", "write_session", "invite_attendees"},
    "ATTENDEE": {"read"},
}


@dataclass(frozen=True)
class CurrentUser:
    id: int
    email: str
    name: str


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_session),
) -> CurrentUser:
    """Resolve the caller from `Authorization: Bearer <token>`.

    Unknown / revoked tokens are rejected here, so a bad or attacker-supplied
    token cannot reach any write endpoint.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.split(" ", 1)[1].strip()
    row = db.execute(
        text("SELECT id, email, name FROM users WHERE api_token = :t"),
        {"t": token},
    ).first()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return CurrentUser(id=row.id, email=row.email, name=row.name)


def role_for_event(db: Session, user_id: int, event_id: int) -> str | None:
    """Return the caller's role on an event, or None if they have none."""
    row = db.execute(
        text(
            "SELECT role FROM event_roles WHERE user_id = :u AND event_id = :e"
        ),
        {"u": user_id, "e": event_id},
    ).first()
    return row.role if row else None


def require_event_capability(
    db: Session, user: CurrentUser, event_id: int, capability: str
) -> str:
    """The chokepoint: allow iff the user's event role grants the capability.

    An attendee calling a write endpoint fails here regardless of what the
    agent (or an injected description) claims. Returns the role on success.
    """
    role = role_for_event(db, user.id, event_id)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this event",
        )
    if capability not in ROLE_CAPABILITIES.get(role, set()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role {role} cannot perform {capability}",
        )
    return role
