# Authorization Chokepoint

One function decides who can do what, driven by **data** rather than
`if role == ...` conditionals spread across handlers. All of it lives in
`app/auth.py`.

## The idea

Adding a role, or changing what a role can do, is a **data change** — you edit
the `ROLE_CAPABILITIES` table, not the handlers. No endpoint has its own
authorization logic; they all call the same chokepoint.

```python
ROLE_CAPABILITIES = {
    "ADMIN":       {"read", "write_session", "invite_attendees",
                    "manage_members", "manage_roles", "view_roster", "view_pii"},
    "CONTRIBUTOR": {"read", "write_session", "invite_attendees"},
    "ATTENDEE":    {"read"},
}
```

Roles are **per-event** (`event_roles`), so the same user can be ADMIN on one
event and ATTENDEE on another. The caller's role is looked up per request:

```python
def role_for_event(db, user_id, event_id) -> str | None:
    ... SELECT role FROM event_roles WHERE user_id = :u AND event_id = :e
```

## The one function

`require_event_capability` is *the* chokepoint. It raises `403` unless the
caller's event role grants the capability:

```python
def require_event_capability(db, user, event_id, capability) -> str:
    role = role_for_event(db, user.id, event_id)
    if role is None:
        raise HTTPException(403, "You do not have access to this event")
    if capability not in ROLE_CAPABILITIES.get(role, set()):
        raise HTTPException(403, f"Role {role} cannot perform {capability}")
    return role
```

A non-raising sibling, `has_capability(...)`, asks the *same* data the same
question — used for response shaping below (no exception).

## It governs two things, not one

The assignment requires the chokepoint to govern **reachability** *and* the
**response body**. Both read the same `ROLE_CAPABILITIES` data:

| Job | Capability | Example |
|---|---|---|
| Which endpoints are reachable | `read`, `write_session`, `invite_attendees`, `manage_members`, `manage_roles` | an ATTENDEE `POST /sessions` → `403` |
| What's in the response body | `view_roster`, `view_pii` | an ATTENDEE can read an event but must **never** see the roster or anyone's email |

`view_roster` / `view_pii` are deliberately *not* about reachability — an event
is readable by an attendee, but the payload is shaped to hide PII and the member
list. Same lookup, second job.

## Authentication, before authorization

`get_current_user` resolves the caller from `Authorization: Bearer <token>` by
matching a row in `users.api_token`. An unknown/absent/revoked token is rejected
here (`401`), so a bad or attacker-supplied token can't reach *any* endpoint —
write or read. Authorization (`role_for_event`) runs after, per event.