"""Planner: turns a validated Intent into resolved `Plan`s via the API.

This is the DETERMINISTIC resolver. The LLM (classifier.py) only understood the
request; here we resolve the real event id, the UTC window, and the room
choice against live data using reads. Writes never happen here — the gated
`AgentLoop` executes the returned plans.

`Plan` is imported from agent.loop so the loop's input contract stays the single
source of truth.
"""

from __future__ import annotations

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


def resolve_event(api: PlatformApi, title_hint: str | None) -> dict:
    """Resolve an event by fuzzy title; the caller must disambiguate."""
    events = api.list_events()
    if title_hint:
        matches = [e for e in events if title_hint.lower() in e["title"].lower()]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"ambiguous event: {[m['title'] for m in matches]}")
        raise ValueError(f"no event matching {title_hint!r}")
    if len(events) == 1:
        return events[0]
    raise ValueError("could not resolve a single event; please name the event")


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
