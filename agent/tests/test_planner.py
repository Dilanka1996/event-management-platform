"""Deterministic tests for Intent -> Plan resolution (no LLM, FakeApi reads)."""

from datetime import datetime

import pytest

from agent.classifier import Intent
from agent.planner import NeedsSlot, intent_to_plan, resolve_event
from agent.scenarios import FakeApi


def test_resolve_event_by_hint():
    api = FakeApi()
    api.events = [
        {"id": 1, "title": "Launch Party", "timezone": "UTC"},
        {"id": 2, "title": "Launch Review", "timezone": "UTC"},
    ]
    # "Launch" ties two titles -> needs the user to choose (offers candidates).
    with pytest.raises(NeedsSlot) as exc:
        resolve_event(api, "Launch")
    assert exc.value.slot == "event"
    assert any("Launch Party" in c for c in exc.value.candidates)
    assert resolve_event(api, "Party")["id"] == 1


def test_resolve_event_exact_beats_prefix():
    """'Event 1' must resolve to 'Event 1', never 'Event 10'/'Event 11'."""
    api = FakeApi()
    api.events = [
        {"id": 1, "title": "Event 1", "timezone": "UTC"},
        {"id": 10, "title": "Event 10", "timezone": "UTC"},
        {"id": 11, "title": "Event 11", "timezone": "UTC"},
        {"id": 2, "title": "Event 2", "timezone": "UTC"},
    ]
    assert resolve_event(api, "Event 1")["id"] == 1
    assert resolve_event(api, "Event 10")["id"] == 10
    assert resolve_event(api, "Event 2")["id"] == 2


def test_resolve_event_duplicate_rows_collapse():
    """The same title stored on multiple rows resolves, not throws ambiguous."""
    api = FakeApi()
    api.events = [
        {"id": 1, "title": "Event 1", "timezone": "UTC"},
        {"id": 52, "title": "Event 1", "timezone": "UTC"},
        {"id": 103, "title": "Event 1", "timezone": "UTC"},
    ]
    assert resolve_event(api, "Event 1")["id"] == 1


def test_resolve_event_no_hint_many_events_asks():
    api = FakeApi()
    api.events = [{"id": i, "title": f"Event {i}", "timezone": "UTC"} for i in range(1, 6)]
    with pytest.raises(NeedsSlot) as exc:
        resolve_event(api, None)
    assert exc.value.slot == "event"
    assert len(exc.value.candidates) <= 8


def test_resolve_event_no_match_asks():
    api = FakeApi()
    api.events = [{"id": 1, "title": "Event 1", "timezone": "UTC"}]
    with pytest.raises(NeedsSlot):
        resolve_event(api, "Nonexistent")


def test_create_session_plan_resolves_utc_and_room_hint():
    api = FakeApi()
    api.events = [{"id": 3, "title": "Event 3", "timezone": "America/New_York"}]
    intent = Intent(action="create_session", slots={
        "event": "Event 3", "title": "Design Review",
        "when": "next Tuesday at 9am", "duration": "45-minute", "room": "any",
    })
    plans = intent_to_plan(api, intent, now=datetime(2025, 3, 10))
    assert len(plans) == 1
    p = plans[0]
    assert p.action == "create_session"
    assert p.params["event_id"] == 3
    assert p.params["start"].startswith("2025-03-11T13:00")  # 9am EDT
    assert p.params["minutes"] == 45
    assert p.params["room_name"] is None  # "any" -> loop picks a free room


def test_create_session_plan_keeps_explicit_room():
    api = FakeApi()
    api.events = [{"id": 1, "title": "Event 1", "timezone": "UTC"}]
    intent = Intent(action="create_session", slots={
        "event": "Event 1", "title": "Sync", "when": "2025-03-11 at 3pm",
        "duration": "1 hour", "room": "Room B",
    })
    p = intent_to_plan(api, intent, now=datetime(2025, 3, 1))[0]
    assert p.params["room_name"] == "Room B"
    assert p.params["minutes"] == 60


def test_invite_plan_validates_emails():
    api = FakeApi()
    api.events = [{"id": 1, "title": "Event 1", "timezone": "UTC"}]
    intent = Intent(action="invite", slots={
        "event": "Event 1", "emails": "a@b.com, c@d.com",
    })
    p = intent_to_plan(api, intent)[0]
    assert p.action == "invite"
    assert p.params["emails"] == ["a@b.com", "c@d.com"]


def test_add_member_plan_validates_role():
    api = FakeApi()
    api.events = [{"id": 1, "title": "Event 1", "timezone": "UTC"}]
    intent = Intent(action="add_member", slots={
        "event": "Event 1", "emails": "carol@example.com", "role": "contributor",
    })
    p = intent_to_plan(api, intent)[0]
    assert p.params["email"] == "carol@example.com"
    assert p.params["role"] == "CONTRIBUTOR"


def test_unknown_action_cannot_plan():
    api = FakeApi()
    with pytest.raises(Exception):
        intent_to_plan(api, Intent(action="unknown", slots={}))
