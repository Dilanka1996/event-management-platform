"""Time handling: local wall-clock <-> UTC instants, DST-safe.

All storage is UTC (TIMESTAMPTZ). Events carry an IANA zone in
`events.timezone`; converting a naive event-local wall-clock time into a
UTC instant requires `zoneinfo` so DST transitions resolve correctly
(e.g. 2025-03-09 02:30 in America/New_York does not exist).
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def to_utc(dt: datetime, tz_name: str) -> datetime:
    """Interpret a naive datetime as event-local wall-clock and return UTC.

    Aware datetimes are normalised to UTC directly (their offset wins).
    """
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc)

    try:
        zone = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as err:
        raise ValueError(f"Unknown timezone: {tz_name!r}") from err

    # The `fold` attribute (default 0) resolves the ambiguous hour that
    # repeats during a DST fall-back to the earlier of the two offsets.
    return dt.replace(tzinfo=zone).astimezone(timezone.utc)


def to_local(dt: datetime, tz_name: str) -> datetime:
    """Render a stored UTC instant as event-local wall-clock time."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        zone = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as err:
        raise ValueError(f"Unknown timezone: {tz_name!r}") from err
    return dt.astimezone(zone)
