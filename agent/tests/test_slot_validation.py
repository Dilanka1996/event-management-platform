"""Deterministic tests for untrusted-slot validation (no LLM)."""

from datetime import datetime

import pytest

from agent.slot_validation import (
    SlotError,
    normalize_duration,
    parse_when,
    validate_emails,
    validate_role,
)


def test_duration_minutes_and_hours():
    assert normalize_duration("45-minute") == 45
    assert normalize_duration("30 minutes") == 30
    assert normalize_duration("1 hour") == 60
    assert normalize_duration("2 hrs") == 120
    assert normalize_duration(None) == 45  # default


def test_emails_from_string_and_list():
    assert validate_emails("a@b.com, c@d.com") == ["a@b.com", "c@d.com"]
    assert validate_emails(["x@y.com"]) == ["x@y.com"]
    # de-dup + lowercase
    assert validate_emails("A@B.com, a@b.com") == ["a@b.com"]


def test_emails_invalid_raises():
    with pytest.raises(SlotError):
        validate_emails("no emails here")
    with pytest.raises(SlotError):
        validate_emails(None)


def test_role_validation():
    assert validate_role("contributor") == "CONTRIBUTOR"
    assert validate_role("ADMIN") == "ADMIN"
    with pytest.raises(SlotError):
        validate_role("SUPERUSER")
    with pytest.raises(SlotError):
        validate_role(None)


def test_parse_when_next_tuesday_in_event_tz():
    # Reference "now": Monday 2025-03-10 00:00 UTC.
    now = datetime(2025, 3, 10, 0, 0)
    start, end = parse_when("next Tuesday at 9am", "America/New_York", 45, now=now)
    # Next Tuesday is 2025-03-11; 9am EDT = 13:00 UTC.
    assert start.startswith("2025-03-11T13:00")
    assert end.startswith("2025-03-11T13:45")


def test_parse_when_dst_boundary():
    # now = 2025-03-08 12:00 UTC = 07:00 EST (03-08) in New York. "tomorrow"
    # resolves in event-local time -> 2025-03-09, which is after spring-forward
    # (EDT, UTC-4), so 9am local -> 13:00 UTC.
    now = datetime(2025, 3, 8, 12, 0)
    start, _ = parse_when("tomorrow at 9am", "America/New_York", 30, now=now)
    assert start.startswith("2025-03-09T13:00")


def test_parse_when_iso_date_and_bare_time():
    now = datetime(2025, 3, 1, 0, 0)
    start, _ = parse_when("2025-03-11 at 2pm", "UTC", 60, now=now)
    assert start.startswith("2025-03-11T14:00")
    start, _ = parse_when("3pm", "UTC", 15, now=now)
    assert start.startswith("2025-03-01T15:00")


def test_parse_when_unparseable_raises():
    with pytest.raises(SlotError):
        parse_when("sometime later", "UTC", 45, now=datetime(2025, 3, 1))
    with pytest.raises(SlotError):
        parse_when(None, "UTC", 45, now=datetime(2025, 3, 1))

