# The Agent's Human-in-the-Loop

How a request gets a human decision before anything is written, and why the
prompt can't be talked around. The mechanism is small enough to read in one
sitting: `agent/gate.py` (policy) + `agent/loop.py` (where it's called) +
`agent/chat.py` (the responder).

## The one rule

> The model understands. **Our code** decides whether a write lands.

The LLM returns a structured `Intent` and never holds a commit-capable path.
The loop calls `gate.check(...)` before **every** write. There is no ungated
write path to talk the model into — which is what makes this a *gate* and not a
prompt instruction.

## What the human actually sees

The gate shows **what will actually be sent**, not a paraphrase. The loop calls
the write with `dry_run=True` first and passes the server's real `summary` to
the prompt:

```
[write] Would invite 2 attendee(s) to event 3
Approve? (y/n):
```

The responder is pluggable — `ApprovalGate(approval_fn)`:

- **REPL:** `_stdin_approval` reads `y`/`yes` from stdin (`agent/chat.py`).
- **Evals:** a *scripted* responder returns a queued list of `True`/`False`
  (`agent/scenarios.py`), so approvals and denials are deterministic in CI.

## Denial is a normal path

A "no" does **not** crash, retry, or silently give up. `gate.check` returns
`Decision(allowed=False, reason=…)`; the loop records the step in `skipped` and
puts a plain-language note in `attention`, which the chat layer prints:

```
CANCELLED — you declined to send those invitations.
[done] completed=[] skipped=['invite']
```

The same is true of a **server-side 403** (e.g. an ATTENDEE token): the call
raises `ApiError`, the step is skipped, and the reason is surfaced — the agent
never reports success it didn't get. (See
`docs/authorization-chokepoint.md` — the server, not the gate, is the reliance
for the injection case.)

## Interruption

A mid-flight correction is *absorbed*, not restarted. `AgentLoop.interrupt(note)`
queues it; the loop checks at a safe point (before commit) and replans just the
affected part — e.g. "wait, use Room B" swaps the room after a fresh free-room
check:

```python
a.interrupt("wait, use Room B")   # absorbed before the write
```

## The destructive double-confirm

`DESTRUCTIVE` actions require **more than a shrug**: a first approval *and* a
second typed confirmation. `delete_event` asks the responder to type `yes`
explicitly:

```
[DESTRUCTIVE] Confirm PERMANENTLY deleting: … 
Type 'yes':
```

If either answer is no → `allowed=False`, nothing executes.

## Two independent people, one decision

The gate is the **human's** decision. The server's authz chokepoint is a
**separate, non-human** check that runs regardless of what the human approved or
what the model believed. A write needs *both*: the human says yes **and** the
caller's role grants the capability. Either can say no independently.

| Layer | Question it answers | Lives in |
|---|---|---|
| Approval gate | "Does the human approve this exact write?" | `agent/gate.py` (our code) |
| Server chokepoint | "Is this token *allowed* to do it?" | `app/auth.py` (the server) |

## End-to-end example

```
> invite user_2@example.com and user_3@example.com to Event 3
→ invite(3, ['user_2@…', 'user_3@…'])
← invite -> {'dry_run': True, 'would_commit': True, 'summary': 'Would invite 2 …'}
⛔ invite -> approved                      # ← the gate, shown above, answered 'y'
→ invite(3, [...])                         # real commit
← invitations sent
[done] completed=['invite']
```

Replace the `y` with `n` and the `→ invite(…, dry_run=False)` line never
happens; you get a `skipped=['invite']` report instead.

## Where to look

| Concern | File |
|---|---|
| Risk tiers, prompt format, double-confirm | `agent/gate.py` |
| When the gate is called; skip/attention/budget | `agent/loop.py` |
| The stdin responder + how notes are printed | `agent/chat.py` |
| Scripted approvals/denials for evals | `agent/scenarios.py` |
