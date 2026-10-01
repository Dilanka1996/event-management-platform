"""Pydantic request/response models — the public API contract.

These are the models FastAPI renders into /openapi.json, which CI verifies
against a committed snapshot (tests/contract/openapi.snapshot.json).
"""

from datetime import datetime

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class EventCreate(BaseModel):
    title: str
    description: str | None = None
    timezone: str = "UTC"
    start_time: datetime | None = None
    end_time: datetime | None = None


class EventUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    timezone: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None


class EventOut(BaseModel):
    id: int
    title: str
    description: str | None
    timezone: str
    start_time: datetime | None
    end_time: datetime | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


class SessionCreate(BaseModel):
    title: str
    room_name: str
    start_time: datetime
    end_time: datetime


class SessionOut(BaseModel):
    id: int
    event_id: int
    title: str
    room_name: str
    start_time: datetime
    end_time: datetime


class FreeRoomOut(BaseModel):
    room_name: str
    free_from: datetime
    free_until: datetime | None


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------


class InvitationCreate(BaseModel):
    emails: list[str] = Field(default_factory=list)


class InvitationOut(BaseModel):
    id: int
    event_id: int
    email: str | None = None  # omitted unless caller has `view_pii`
    status: str
    created_at: datetime


class InvitationPage(BaseModel):
    items: list[InvitationOut]
    next_cursor: int | None = None


# ---------------------------------------------------------------------------
# Members / roles
# ---------------------------------------------------------------------------


class MemberAdd(BaseModel):
    email: str
    role: str  # ADMIN | CONTRIBUTOR | ATTENDEE


class MemberOut(BaseModel):
    user_id: int
    email: str | None = None  # omitted unless caller has `view_pii`
    name: str
    role: str


class MemberPage(BaseModel):
    items: list[MemberOut]


# ---------------------------------------------------------------------------
# Preview (dry-run) envelope
# ---------------------------------------------------------------------------


class PreviewResult(BaseModel):
    """Returned by `?dry_run=true` writes: what WOULD happen, without committing."""

    dry_run: bool = True
    would_commit: bool
    action: str
    summary: str
    details: dict = Field(default_factory=dict)
