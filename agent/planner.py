"""Planner: turns an NL request into a Plan, resolving facts via the API.

Deterministic by default (no model needed) so CI evals replay stably.
A real LLM backend can be plugged in behind the same `plan()` interface, but
the approval gate and budget live in the loop, not the model — so swapping the
planner never weakens the safety guarantees.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from agent.loop import Plan
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
    if len(events) == 1:
        return events[0]
    raise ValueError("could not resolve a single event")


def local_to_utc_iso(local_dt: datetime, tz_name: str) -> str:
    """Resolve a naive event-local wall-clock time into a UTC ISO-8601 string."""
    return local_dt.replace(tzinfo=ZoneInfo(tz_name)).astimezone(
        ZoneInfo("UTC")
    ).isoformat()


def plan_schedule_review(
    api: PlatformApi,
    event_hint: str,
    local_date_iso: str,
    local_time: str,
    minutes: int = 45,
    title: str = "Design Review",
) -> Plan:
    """Compose the classic request: resolve event + local date + free room."""
    event = resolve_event(api, event_hint)
    tz = event["timezone"]
    naive = datetime.fromisoformat(f"{local_date_iso}T{local_time}")
    start_utc = naive.replace(tzinfo=ZoneInfo(tz)).astimezone(ZoneInfo("UTC"))
    end_utc = start_utc + timedelta(minutes=minutes)
    return Plan(
        action="create_session",
        params={
            "event_id": event["id"],
            "intent": f"{minutes}-min {title} on {local_date_iso} {local_time} ({tz})",
            "title": title,
            "start": start_utc.isoformat(),
            "end": end_utc.isoformat(),
            "minutes": minutes,
            "start_date": local_date_iso,
        },
    )
