"""Time handling: local wall-clock <-> UTC, DST-safe."""

from datetime import datetime

import pytest

from app.timeutil import to_local, to_utc


def test_naive_local_to_utc_standard_time():
    # Jan = EST (UTC-5)
    utc = to_utc(datetime(2025, 1, 15, 9, 0), "America/New_York")
    assert utc.isoformat() == "2025-01-15T14:00:00+00:00"


def test_naive_local_to_utc_after_spring_forward():
    # After 2025-03-09 02:00, NY is EDT (UTC-4)
    utc = to_utc(datetime(2025, 3, 15, 9, 0), "America/New_York")
    assert utc.isoformat() == "2025-03-15T13:00:00+00:00"


def test_zone_without_dst():
    utc = to_utc(datetime(2025, 3, 15, 9, 0), "Asia/Kolkata")
    assert utc.isoformat() == "2025-03-15T03:30:00+00:00"


def test_aware_datetime_wins():
    aware = datetime.fromisoformat("2025-06-01T10:00:00+02:00")
    assert to_utc(aware, "UTC").isoformat() == "2025-06-01T08:00:00+00:00"


def test_round_trip():
    local = datetime(2025, 11, 5, 8, 30)  # after fall-back, EST
    utc = to_utc(local, "America/New_York")
    back = to_local(utc, "America/New_York")
    assert back.replace(tzinfo=None) == local


def test_unknown_zone_raises():
    with pytest.raises(ValueError):
        to_utc(datetime(2025, 1, 1, 0, 0), "Mars/Olympus")
