"""Event CRUD. Every route resolves event_id from the path (never the body),
then goes through the chokepoint before touching data."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import CurrentUser, get_current_user, require_event_capability
from app.db import get_session
from app.schemas import EventCreate, EventOut, EventUpdate
from app.timeutil import to_utc

router = APIRouter(prefix="/events", tags=["events"])

_COLS = "id, title, description, timezone, start_time, end_time, created_at"


def _row_to_event(row) -> EventOut:
    return EventOut(
        id=row.id,
        title=row.title,
        description=row.description,
        timezone=row.timezone,
        start_time=row.start_time,
        end_time=row.end_time,
        created_at=row.created_at,
    )


@router.post("", response_model=EventOut, status_code=status.HTTP_201_CREATED)
def create_event(
    payload: EventCreate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> EventOut:
    """Create an event. The creator is auto-granted ADMIN via event_roles."""
    start = to_utc(payload.start_time, payload.timezone) if payload.start_time else None
    end = to_utc(payload.end_time, payload.timezone) if payload.end_time else None

    row = db.execute(
        text(
            f"INSERT INTO events (title, description, timezone, start_time, end_time) "
            f"VALUES (:t, :d, :tz, :s, :e) RETURNING {_COLS}"
        ),
        {
            "t": payload.title,
            "d": payload.description,
            "tz": payload.timezone,
            "s": start,
            "e": end,
        },
    ).one()

    # Creator becomes ADMIN — the role grant is data, so the chokepoint sees it.
    db.execute(
        text(
            "INSERT INTO event_roles (user_id, event_id, role) "
            "VALUES (:u, :e, 'ADMIN') ON CONFLICT (user_id, event_id) DO NOTHING"
        ),
        {"u": user.id, "e": row.id},
    )
    db.commit()
    return _row_to_event(row)


@router.get("", response_model=list[EventOut])
def list_events(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> list[EventOut]:
    """Events the caller has any role on."""
    rows = db.execute(
        text(
            f"SELECT e.{_COLS.replace(', ', ', e.')} FROM events e "
            "JOIN event_roles r ON r.event_id = e.id "
            "WHERE r.user_id = :u ORDER BY e.id"
        ),
        {"u": user.id},
    ).all()
    return [_row_to_event(r) for r in rows]


@router.get("/{event_id}", response_model=EventOut)
def get_event(
    event_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> EventOut:
    require_event_capability(db, user, event_id, "read")
    row = db.execute(
        text(f"SELECT {_COLS} FROM events WHERE id = :e"), {"e": event_id}
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return _row_to_event(row)


@router.patch("/{event_id}", response_model=EventOut)
def update_event(
    event_id: int,
    payload: EventUpdate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> EventOut:
    """Partial update. Requires manage_roles (ADMIN)."""
    require_event_capability(db, user, event_id, "manage_roles")

    current = db.execute(
        text("SELECT timezone, start_time, end_time FROM events WHERE id = :e"),
        {"e": event_id},
    ).first()
    if current is None:
        raise HTTPException(status_code=404, detail="Event not found")

    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        row = db.execute(
            text(f"SELECT {_COLS} FROM events WHERE id = :e"), {"e": event_id}
        ).one()
        return _row_to_event(row)

    tz = fields.get("timezone", current.timezone)
    for key in ("start_time", "end_time"):
        if fields.get(key) is not None:
            fields[key] = to_utc(fields[key], tz)

    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    params = {**fields, "e": event_id}
    row = db.execute(
        text(f"UPDATE events SET {set_clause} WHERE id = :e RETURNING {_COLS}"),
        params,
    ).one()
    db.commit()
    return _row_to_event(row)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> None:
    """Destructive. Requires manage_roles (ADMIN). Cascades to sessions/roles."""
    require_event_capability(db, user, event_id, "manage_roles")
    db.execute(text("DELETE FROM events WHERE id = :e"), {"e": event_id})
    db.commit()
