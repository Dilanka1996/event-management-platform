"""Sessions (room + time blocks) and the free-room lookup the agent composes with."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import CurrentUser, get_current_user, require_event_capability
from app.db import get_session
from app.schemas import FreeRoomOut, PreviewResult, SessionCreate, SessionOut
from app.timeutil import to_utc

router = APIRouter(prefix="/events/{event_id}", tags=["sessions"])


def _overlap(
    db: Session, event_id: int, room: str, start, end, exclude_id: int | None = None
):
    """Return the conflicting session row in `room`, if any."""
    sql = (
        "SELECT id, title, room_name, start_time, end_time FROM sessions "
        "WHERE event_id = :e AND room_name = :r "
        "AND start_time < :end AND end_time > :start"
    )
    params = {"e": event_id, "r": room, "start": start, "end": end}
    if exclude_id is not None:
        sql += " AND id <> :x"
        params["x"] = exclude_id
    return db.execute(text(sql), params).first()


@router.post(
    "/sessions",
    response_model=SessionOut | PreviewResult,
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    event_id: int,
    payload: SessionCreate,
    dry_run: bool = False,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    require_event_capability(db, user, event_id, "write_session")

    tz = db.execute(
        text("SELECT timezone FROM events WHERE id = :e"), {"e": event_id}
    ).scalar_one_or_none()
    if tz is None:
        raise HTTPException(status_code=404, detail="Event not found")

    start = to_utc(payload.start_time, tz)
    end = to_utc(payload.end_time, tz)
    if end <= start:
        raise HTTPException(status_code=422, detail="end_time must be after start_time")

    clash = _overlap(db, event_id, payload.room_name, start, end)
    if clash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": f"Room {payload.room_name!r} is busy",
                "conflict_session_id": clash.id,
                "conflict_title": clash.title,
            },
        )

    if dry_run:
        return PreviewResult(
            would_commit=True,
            action="create_session",
            summary=(
                f"Would book {payload.room_name!r} for {payload.title!r} "
                f"({start.isoformat()} → {end.isoformat()} UTC)"
            ),
            details={"event_id": event_id, "room_name": payload.room_name},
        )

    row = db.execute(
        text(
            "INSERT INTO sessions (event_id, title, room_name, start_time, end_time) "
            "VALUES (:e, :t, :r, :s, :en) "
            "RETURNING id, event_id, title, room_name, start_time, end_time"
        ),
        {
            "e": event_id,
            "t": payload.title,
            "r": payload.room_name,
            "s": start,
            "en": end,
        },
    ).one()
    db.commit()
    return SessionOut(**row._mapping)


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(
    event_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> list[SessionOut]:
    require_event_capability(db, user, event_id, "read")
    rows = db.execute(
        text(
            "SELECT id, event_id, title, room_name, start_time, end_time "
            "FROM sessions WHERE event_id = :e ORDER BY start_time"
        ),
        {"e": event_id},
    ).all()
    return [SessionOut(**r._mapping) for r in rows]


@router.get("/rooms/free", response_model=list[FreeRoomOut])
def free_rooms(
    event_id: int,
    start: str,
    minutes: int = 45,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> list[FreeRoomOut]:
    """Which rooms are free for `minutes` starting at ISO-8601 `start`.

    This is the query the agent composes with: resolve event + local time +
    a genuinely free room, all before proposing any write.
    """
    require_event_capability(db, user, event_id, "read")

    from datetime import datetime, timedelta, timezone

    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail="start must be ISO-8601")
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(minutes=minutes)

    # Every room ever used on this event.
    rooms = [
        r.room_name
        for r in db.execute(
            text("SELECT DISTINCT room_name FROM sessions WHERE event_id = :e"),
            {"e": event_id},
        ).all()
    ]

    free: list[FreeRoomOut] = []
    for room in rooms:
        busy = _overlap(db, event_id, room, start_dt, end_dt)
        if busy is None:
            free.append(
                FreeRoomOut(
                    room_name=room, free_from=start_dt, free_until=end_dt
                )
            )
    return free
