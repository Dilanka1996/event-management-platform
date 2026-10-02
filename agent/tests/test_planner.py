"""Deterministic tests for Intent -> Plan resolution (no LLM, FakeApi reads)."""

from datetime import datetime

import pytest

from agent.classifier import Intent
from agent.planner import intent_to_plan, resolve_event
from agent.scenarios import FakeApi


def test_resolve_event_by_hint():
    api = FakeApi()
    api.events = [
        {"id": 1, "title": "Launch Party", "timezone": "UTC"},
        {"id": 2, "title": "Launch Review", "timezone": "UTC"},
    ]
    with pytest.raises(ValueError, match="ambiguous"):
        resolve_event(api, "Launch")
    assert resolve_event(api, "Party")["id"] == 1


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
