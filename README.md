# event-management-platform

A small event-management backend (FastAPI + PostgreSQL) plus a thin, gated AI
agent that drives it over the public API.

## What's here

| Area | Where | Notes |
|------|-------|-------|
| CRUD API | `app/routers/` | events, sessions, invitations, members |
| Authorization chokepoint | `app/auth.py` | data-driven, governs reachability **and** the response body |
| OpenAPI contract | `tests/test_openapi_contract.py` + `tests/contract/openapi.snapshot.json` | CI verifies the server honours the contract |
| Time handling | `app/timeutil.py` | local wall-clock ↔ UTC, DST-safe |
| Seed data | `scripts/seed_data.py` | 50 events / 5k users / 50k invitations, multiple timezones |
| Agent | `agent/` | bounded loop, approval gate, legible trace, ~15 scenarios |

## Quick start
