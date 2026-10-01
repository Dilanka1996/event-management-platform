"""Authorization tests — reachability AND response-body shaping.

The headline requirement: an ATTENDEE can read an event but must NEVER see the
roster or anyone's email. This is proven here.
"""

import uuid

import pytest
from sqlalchemy import text

from app.db import engine
from tests.conftest import auth


def _mk_user(email, token):
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO users (email, name, api_token) VALUES (:e, :n, :t) "
                "ON CONFLICT (email) DO UPDATE SET api_token = EXCLUDED.api_token "
                "RETURNING id"
            ),
            {"e": email, "n": email, "t": token},
        ).one()
    return row.id


def _mk_event(title, tz="UTC"):
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO events (title, timezone, start_time, end_time) "
                "VALUES (:t, :tz, now(), now() + interval '1 day') RETURNING id"
            ),
            {"t": title, "tz": tz},
        ).one()
    return row.id


def _grant(user_id, event_id, role):
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO event_roles (user_id, event_id, role) VALUES (:u, :e, :r) "
                "ON CONFLICT (user_id, event_id) DO UPDATE SET role = EXCLUDED.role"
            ),
            {"u": user_id, "e": event_id, "r": role},
        )


@pytest.fixture
def fixture_event():
    tag = uuid.uuid4().hex[:8]
    admin = _mk_user(f"admin_{tag}@x.com", f"tok_a_{tag}")
    contributor = _mk_user(f"contrib_{tag}@x.com", f"tok_c_{tag}")
    attendee = _mk_user(f"attend_{tag}@x.com", f"tok_t_{tag}")
    event_id = _mk_event(f"Authz Test {tag}")
    _grant(admin, event_id, "ADMIN")
    _grant(contributor, event_id, "CONTRIBUTOR")
    _grant(attendee, event_id, "ATTENDEE")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO invitations (event_id, email, status) "
                "VALUES (:e, 'someone@x.com', 'PENDING') ON CONFLICT DO NOTHING"
            ),
            {"e": event_id},
        )
    return {
        "event_id": event_id,
        "admin": admin,
        "contributor": contributor,
        "attendee": attendee,
        "tokens": {
            "admin": f"tok_a_{tag}",
            "contributor": f"tok_c_{tag}",
            "attendee": f"tok_t_{tag}",
        },
    }


def test_no_token_is_401(client):
    assert client.get("/events").status_code == 401


def test_bad_token_is_401(client):
    assert client.get("/events", headers=auth("nope")).status_code == 401


def test_attendee_can_read_event(client, fixture_event):
    r = client.get(f"/events/{fixture_event['event_id']}",
                   headers=auth(fixture_event["tokens"]["attendee"]))
    assert r.status_code == 200
    assert r.json()["title"].startswith("Authz Test")


def test_attendee_cannot_see_roster(client, fixture_event):
    """Attendee reading members must get 403 — never the roster."""
    r = client.get(f"/events/{fixture_event['event_id']}/members",
                   headers=auth(fixture_event["tokens"]["attendee"]))
    assert r.status_code == 403


def test_attendee_emails_are_redacted_in_invitations(client, fixture_event):
    """Even where an attendee CAN read (invitations), no emails leak."""
    r = client.get(
        f"/events/{fixture_event['event_id']}/invitations",
        headers=auth(fixture_event["tokens"]["attendee"]),
    )
    assert r.status_code == 200
    for item in r.json()["items"]:
        assert item["email"] is None


def test_admin_sees_roster_and_emails(client, fixture_event):
    r = client.get(f"/events/{fixture_event['event_id']}/members",
                   headers=auth(fixture_event["tokens"]["admin"]))
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(i["email"] for i in items)  # admin can see PII


def test_attendee_cannot_write_session(client, fixture_event):
    body = {
        "title": "Hack",
        "room_name": "Room Z",
        "start_time": "2025-06-01T10:00:00+00:00",
        "end_time": "2025-06-01T11:00:00+00:00",
    }
    r = client.post(
        f"/events/{fixture_event['event_id']}/sessions",
        headers=auth(fixture_event["tokens"]["attendee"]),
        json=body,
    )
    assert r.status_code == 403


def test_contributor_can_write_session(client, fixture_event):
    body = {
        "title": "Workshop",
        "room_name": "Room Y",
        "start_time": "2025-06-01T10:00:00+00:00",
        "end_time": "2025-06-01T11:00:00+00:00",
    }
    r = client.post(
        f"/events/{fixture_event['event_id']}/sessions",
        headers=auth(fixture_event["tokens"]["contributor"]),
        json=body,
    )
    assert r.status_code == 201


def test_contributor_cannot_manage_members(client, fixture_event):
    """Adding a role requires manage_members, which CONTRIBUTOR lacks."""
    r = client.post(
        f"/events/{fixture_event['event_id']}/members",
        headers=auth(fixture_event["tokens"]["contributor"]),
        json={"email": "someone@x.com", "role": "ADMIN"},
    )
    assert r.status_code == 403
