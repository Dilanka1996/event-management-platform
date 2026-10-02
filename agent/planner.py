"""Planner: turns a validated Intent into resolved `Plan`s via the API.

This is the DETERMINISTIC resolver. The LLM (classifier.py) only understood the
request; here we resolve the real event id, the UTC window, and the room
choice against live data using reads. Writes never happen here — the gated
`AgentLoop` executes the returned plans.

`Plan` is imported from agent.loop so the loop's input contract stays the single
source of truth.
"""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from agent.classifier import Intent
from agent.loop import Plan
from agent.slot_validation import (
    SlotError,
    normalize_duration,
    parse_when,
    validate_emails,
    validate_role,
)
from agent.tools import PlatformApi


class NeedsSlot(SlotError):
    """A required slot is missing/ambiguous; the REPL asks for it and merges
    the answer into the pending intent. `candidates` optionally offers choices."""

    def __init__(self, slot: str, message: str, candidates: list[str] | None = None):
        super().__init__(message)
        self.slot = slot
        self.candidates = candidates or []


def _title_rank(title: str, hint: str) -> int | None:
    """Rank how well `title` matches `hint`; None means no match.

    Ordered so an EXACT title beats a prefix, which beats a substring — so
    "Event 1" matches "Event 1" (rank 0) and NEVER "Event 10" when an exact
    match exists (the loose substring match loses on rank).
    """
    t = title.strip().lower()
    h = hint.strip().lower()
    if not h:
        return None
    if re.sub(r"\s+", " ", t) == re.sub(r"\s+", " ", h):
        return 0
    # whole-word substring: hint bounded by non-word chars, e.g. "event 3"
    if re.search(rf"(?<!\w){re.escape(h)}(?!\w)", t):
        return 1
    if t.startswith(h):
        return 2
    if h in t:
        return 3
    return None


def resolve_event(api: PlatformApi, title_hint: str | None) -> dict:
    """Resolve an event by fuzzy title.

    Exact matches win over prefixes, which win over loose substrings, so
    "Event 1" resolves to "Event 1" (not the "Event 1x" family).

    Raises `NeedsSlot("event", ...)` when the user must name/choose an event:
    no hint with many events, no match, or genuinely-tied candidates.
    """
    events = api.list_events()
    if not events:
        raise NeedsSlot("event", "there are no events to choose from")

    if title_hint:
        scored = [
            (rank, e)
            for e in events
            if (rank := _title_rank(e["title"], title_hint)) is not None
        ]
        if scored:
            best_rank = min(rank for rank, _ in scored)
            winners = [e for rank, e in scored if rank == best_rank]
            # Collapse duplicate rows that share the same title text.
            uniq: dict[str, dict] = {}
            for e in winners:
                uniq.setdefault(e["title"].strip().lower(), e)
            winners = list(uniq.values())
            if len(winners) == 1:
                return winners[0]
            raise NeedsSlot(
                "event",
                f"which event did you mean by {title_hint!r}?",
                candidates=[f"#{e['id']}  {e['title']}" for e in winners],
            )
        raise NeedsSlot(
            "event",
            f"no event matches {title_hint!r}; please name the event",
        )

    if len(events) == 1:
        return events[0]
    raise NeedsSlot(
        "event",
        "which event is this for? please name the event",
        candidates=[f"#{e['id']}  {e['title']}" for e in events[:8]],
    )


def local_to_utc_iso(local_dt: datetime, tz_name: str) -> str:
    """Resolve a naive event-local wall-clock time into a UTC ISO-8601 string."""
    return local_dt.replace(tzinfo=ZoneInfo(tz_name)).astimezone(
        ZoneInfo("UTC")
    ).isoformat()


def intent_to_plan(
    api: PlatformApi,
    intent: Intent,
    *,
    now: datetime | None = None,
) -> list[Plan]:
    """Resolve a classified Intent into executable Plan(s).

    Raises SlotError / ValueError on anything that needs the user to clarify.
    The room is resolved HERE (a read) so the loop can still re-check it after
    an interrupt.
    """
    slots = intent.slots
    if intent.action == "create_session":
        return [_plan_create_session(api, slots, now)]
    if intent.action == "invite":
        return [_plan_invite(api, slots)]
    if intent.action == "add_member":
        return [_plan_add_member(api, slots)]
    raise SlotError(f"action {intent.action!r} cannot be turned into a plan")


def _plan_create_session(api: PlatformApi, slots: dict, now: datetime | None) -> Plan:
    event = resolve_event(api, slots.get("event"))
    tz = event["timezone"]
    minutes = normalize_duration(slots.get("duration"))
    start_utc, end_utc = parse_when(slots.get("when"), tz, minutes, now=now)

    title = (slots.get("title") or "Session").strip() or "Session"

    # Room hint: an explicit name, or None meaning "any free". "any" -> None.
    room_hint = slots.get("room")
    if isinstance(room_hint, str) and room_hint.strip().lower() in {"", "any", "free", "whichever"}:
        room_hint = None

    return Plan(
        action="create_session",
        params={
            "event_id": event["id"],
            "intent": f"{minutes}-min {title} at {start_utc}",
            "title": title,
            "start": start_utc,
            "end": end_utc,
            "minutes": minutes,
            "room_name": room_hint,  # may be None -> loop picks a free room
        },
    )


def _plan_invite(api: PlatformApi, slots: dict) -> Plan:
    event = resolve_event(api, slots.get("event"))
    emails = validate_emails(slots.get("emails"))
    return Plan(
        action="invite",
        params={"event_id": event["id"], "emails": emails},
    )


def _plan_add_member(api: PlatformApi, slots: dict) -> Plan:
    event = resolve_event(api, slots.get("event"))
    emails = validate_emails(slots.get("emails"))
    role = validate_role(slots.get("role"))
    return Plan(
        action="add_member",
        params={"event_id": event["id"], "email": emails[0], "role": role},
    )
