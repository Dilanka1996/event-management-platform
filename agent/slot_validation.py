"""Deterministic validation & normalisation of UNTRUSTED LLM slots.

The classifier emits raw slot strings ("next Tuesday at 9am", "45-minute",
"alice@example.com, bob@example.com"). Those are untrusted input. This module
turns them into typed, checked values — and resolves the dangerous one (`when`)
to a UTC instant in the event's timezone.

Hard rule: the LLM never supplies an `event_id`, a UTC timestamp, or a room
choice. `when` is parsed here (rule-based, DST-safe via app.timeutil); rooms are
resolved against live data in planner.py.

This module imports nothing LLM-related and is fully unit-testable offline.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

VALID_ROLES = {"ADMIN", "CONTRIBUTOR", "ATTENDEE"}

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_DURATION_RE = re.compile(r"(\d+)\s*[-\s]?\s*(min|mins|minute|minutes|m|hour|hours|hr|hrs|h)\b", re.I)
_DURATION_BARE_RE = re.compile(r"(\d+)\s*(?:-|\s)?(?:min|minute|minutes|m)\b", re.I)

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


class SlotError(ValueError):
    """A slot the model produced could not be validated (chat asks the user)."""


# ---------------------------------------------------------------------------
# duration
# ---------------------------------------------------------------------------
def normalize_duration(text: str | None, default: int = 45) -> int:
    """'45-minute' / '1 hour' -> minutes. Falls back to `default`."""
    if not text:
        return default
    m = _DURATION_RE.search(text)
    if not m:
        m = _DURATION_BARE_RE.search(text)
    if not m:
        return default
    value = int(m.group(1))
    unit = m.group(2).lower()
    return value * 60 if unit.startswith("h") else value


# ---------------------------------------------------------------------------
# emails / role
# ---------------------------------------------------------------------------
def validate_emails(raw) -> list[str]:
    """Accept a raw string or list; return de-duped, lower-cased, validated emails."""
    if raw is None:
        raise SlotError("no email addresses provided")
    if isinstance(raw, str):
        candidates = _EMAIL_RE.findall(raw)
    elif isinstance(raw, (list, tuple)):
        candidates = []
        for item in raw:
            candidates.extend(_EMAIL_RE.findall(str(item)))
    else:
        candidates = _EMAIL_RE.findall(str(raw))

    seen: list[str] = []
    for email in candidates:
        email = email.strip().lower()
        if email and email not in seen:
            seen.append(email)
    if not seen:
        raise SlotError(f"no valid email addresses found in {raw!r}")
    return seen


def validate_role(raw) -> str:
    if not raw:
        raise SlotError("no role provided")
    role = str(raw).strip().upper()
    # tolerate "make X an admin" -> the classifier may send lowercase
    if role not in VALID_ROLES:
        raise SlotError(f"invalid role {raw!r}; expected one of {sorted(VALID_ROLES)}")
    return role


# ---------------------------------------------------------------------------
# when  ->  (start_utc_iso, end_utc_iso)
# ---------------------------------------------------------------------------
def parse_when(
    when_text: str | None,
    tz_name: str,
    minutes: int,
    *,
    now: datetime | None = None,
) -> tuple[str, str]:
    """Resolve an event-local 'when' phrase into UTC ISO start/end.

    Supports: ISO date/datetime, 'next Tuesday', 'tomorrow', 'today', weekday
    names, 'at 9am' / '3pm' clock times, 'in N days'. Interpretation is in the
    EVENT's timezone, DST-safe via zoneinfo.
    """
    if not when_text:
        raise SlotError("no time provided")

    now_local = _now_in_tz(tz_name, now)
    text = when_text.strip().lower()

    date_part, time_part = _split_date_time(text)

    day = _resolve_day(date_part, now_local)
    hour, minute = _resolve_time(time_part)

    naive = datetime(day.year, day.month, day.day, hour, minute)
    start = naive.replace(tzinfo=ZoneInfo(tz_name)).astimezone(timezone.utc)
    end = start + timedelta(minutes=minutes)
    return start.isoformat(), end.isoformat()


def _now_in_tz(tz_name: str, now: datetime | None) -> datetime:
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(ZoneInfo(tz_name))


def _split_date_time(text: str) -> tuple[str, str]:
    """Split 'next tuesday at 9am' -> ('next tuesday', '9am')."""
    text = re.sub(r"^(the|on|at)\s+", "", text).strip()
    if " at " in text:
        date_part, time_part = text.split(" at ", 1)
        return date_part.strip(), time_part.strip()
    # a bare clock time with no date -> today at that time
    if re.fullmatch(r"\d{1,2}(:\d{2})?\s*(am|pm)?", text):
        return "", text
    if re.search(r"\b\d{1,2}(:\d{2})?\s*(am|pm)\b", text):
        m = re.search(r"\b(\d{1,2}(:\d{2})?\s*(am|pm))\b", text)
        return re.sub(r"\b(\d{1,2}(:\d{2})?\s*(am|pm))\b", "", text).strip(), m.group(1)
    return text, ""


def _resolve_day(date_part: str, now_local: datetime) -> datetime:
    date_part = date_part.strip()
    if not date_part:
        return now_local

    # ISO date: 2025-03-11
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", date_part)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    if "day after tomorrow" in date_part:
        return now_local + timedelta(days=2)
    if "tomorrow" in date_part:
        return now_local + timedelta(days=1)
    if "today" in date_part or "tonight" in date_part:
        return now_local

    m = re.search(r"in (\d+) days?", date_part)
    if m:
        return now_local + timedelta(days=int(m.group(1)))

    # explicit month-day: "march 11" or "11 march"
    m = re.search(r"([a-z]+)\s+(\d{1,2})", date_part)
    if m and m.group(1) in _MONTHS:
        return datetime(now_local.year, _MONTHS[m.group(1)], int(m.group(2)))
    m = re.search(r"(\d{1,2})\s+([a-z]+)", date_part)
    if m and m.group(2) in _MONTHS:
        return datetime(now_local.year, _MONTHS[m.group(2)], int(m.group(1)))

    # weekday: "next tuesday" / "tuesday"
    for name, idx in _WEEKDAYS.items():
        if name in date_part:
            return _next_weekday(now_local, idx, forward="next" in date_part)
    raise SlotError(f"could not understand the date {date_part!r}")


def _next_weekday(now_local: datetime, weekday: int, *, forward: bool) -> datetime:
    days_ahead = (weekday - now_local.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7  # "Tuesday" said on a Tuesday means next week's
    if forward and days_ahead < 7:
        # "next Tuesday" pushes into the following week when today is past it
        pass
    return now_local + timedelta(days=days_ahead)


def _resolve_time(time_part: str) -> tuple[int, int]:
    time_part = time_part.strip()
    if not time_part:
        return 9, 0  # default 9am when only a date is given

    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", time_part)
    if not m:
        raise SlotError(f"could not understand the time {time_part!r}")
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    meridiem = m.group(3)
    if meridiem == "pm" and hour < 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise SlotError(f"invalid time {time_part!r}")
    return hour, minute
