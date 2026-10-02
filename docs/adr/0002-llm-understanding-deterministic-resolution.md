# ADR 0002 — LLM for understanding, deterministic code for resolution

## Status
Accepted

## Context
We need to turn free-form text ("schedule a 45-minute design review next
Tuesday at 9 am in whichever room is free") into an executable plan. Two
sub-problems hide inside that: (1) understanding *what* and (2) resolving
*which/ when / where*. Options ranged from an all-LLM approach to an
all-deterministic parser.

The three slots that matter most are also the most dangerous:
`event_id`, the UTC timestamp (timezone/DST), and the room choice ("whichever
is free" must be verified against live data). Getting these wrong is a silent
failure — the worst kind for this assignment.

## Decision
Split the pipeline at the trust boundary:

1. **LLM (`agent/classifier.py`, Ollama `llama3.2:3b`)** does understanding and
   slot *extraction only* — returns a schema-constrained `Intent(action, slots)`
   with **raw hints** ("next Tuesday at 9am", "any", "alice@b.com").
2. **Deterministic code (`agent/slot_validation.py`, `agent/planner.py`)** does
   all resolution/validation: emails, role, duration, and **`parse_when`** →
   UTC ISO in the event's timezone (DST-safe); `resolve_event` → real id;
   room resolved from live `free_rooms`.

The LLM is never allowed to emit an `event_id`, a UTC timestamp, or a room
choice.

## Rejected alternative
**Let the LLM emit resolved values directly** (ask the model for `event_id`,
ISO datetimes, and a room name). It is fewer moving parts and works "most of
the time."

Rejected because:
- Small local models **silently get calendar/DST arithmetic wrong** — a wrong
  instant is a plausible-looking, hard-to-catch failure.
- The model would have to **invent/hallucinate IDs** it can't know unless we
  feed it event data — which reintroduces the injection surface the seeded
  "Hostile Data Demo" description exists to test.
- It makes the dangerous slots **nondeterministic and untestable** — we could
  not assert "next Tuesday 9am NY → 13:00Z" with an exact test.

## Why
- "The LLM proposes; the resolver confirms." Fuzzy *understanding* is where the
  LLM earns its place; *correctness* of IDs/times/rooms is code's job.
- The dangerous slots become **provable**: `parse_when` is unit-tested against
  exact expected instants, including the 2025-03-09 spring-forward boundary.
- It removes the injection surface from the understanding step: the classifier
  prompt contains only the user's utterance, never stored event text.

## Consequences
- More code than "one LLM call returns everything": a validator + a date
  grammar to maintain.
- `Intent.slots` is treated as **untrusted input** (validated like a request
  body), and slot failures route to "ask the user," not a guess.
- The understanding layer stays swappable (a different model, or a classifier)
  without touching resolution or the gate.
