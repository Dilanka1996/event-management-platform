"""Interactive chat over the event-management API.

Pipeline (L1 design):
    text
      -> agent.classifier   (OpenAI LLM: understanding + slot extraction)
      -> agent.slot_validation / agent.planner (deterministic: resolve
         event id, UTC window, room — via reads)
      -> agent.loop.AgentLoop (governor: preview -> gate -> commit -> trace)

The LLM only produces a structured `Intent`; the resolver confirms the
dangerous slots; the loop owns the six safety guarantees. The model cannot
commit anything.

Usage:
    python -m agent.chat                # interactive REPL
    python -m agent.chat "schedule ..." # one-shot

Env:
    EMP_BASE_URL     default http://localhost:8000
    EMP_TOKEN        default tok_1
    LLM_MODEL        default gpt-4o-mini
    OPENAI_API_KEY   required
    OPENAI_BASE_URL  optional (OpenAI-compatible endpoint)
"""

from __future__ import annotations

import os
import sys

from agent.classifier import ClassifierError, IntentClassifier
from agent.gate import ApprovalGate
from agent.loop import AgentLoop
from agent.planner import NeedsSlot, intent_to_plan, resolve_event
from agent.slot_validation import SlotError
from agent.tools import PlatformApi


def _stdin_approval(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() in {"y", "yes"}
    except EOFError:
        return False


def build_components(budget: int = 8):
    base = os.getenv("EMP_BASE_URL", "http://localhost:8000")
    token = os.getenv("EMP_TOKEN", "tok_1")
    api = PlatformApi(base, token)
    gate = ApprovalGate(_stdin_approval)
    loop = AgentLoop(api, gate, budget=budget)
    classifier = IntentClassifier()
    return api, loop, classifier


def _render_reads(api: PlatformApi, intent) -> None:
    """Read-only actions are rendered directly (no gate needed).

    `intent` (not just the action) is passed so `list_sessions` can use the
    `event` slot the classifier extracted — previously the slot was discarded
    and every request printed the "specify an event" hint.
    """
    if intent.action == "list_events":
        events = api.list_events()
        if not events:
            print("(no events)")
        for e in events:
            print(f"  #{e['id']}  {e['title']}  [{e['timezone']}]")
    elif intent.action == "list_sessions":
        hint = intent.slots.get("event")
        # Resolve the event deterministically; may raise NeedsSlot -> caller asks.
        event = resolve_event(api, hint)
        sessions = api.list_sessions(event["id"])
        if not sessions:
            print(f"(no sessions on #{event['id']} {event['title']})")
            return
        print(f"Sessions on #{event['id']} {event['title']}:")
        for s in sessions:
            print(
                f"  {s['start_time']} → {s['end_time']}  "
                f"{s['room_name']}  {s['title']}"
            )


# ---------------------------------------------------------------------------
# Pending-slot flow
#
# When the resolver needs a slot (e.g. "which event?"), we DO NOT re-classify
# the next line from scratch — that would lose the title/when/duration we
# already understood. Instead we keep the half-built `Intent` here, ask for the
# one missing slot, and merge the user's answer in deterministically.
# ---------------------------------------------------------------------------
def _ask_for_slot(err: NeedsSlot) -> None:
    print(f"I need the {err.slot}: {err}")
    for line in err.candidates:
        print(f"  {line}")


# A short, unambiguous answer to "which event?" (the only slot we currently ask
# for) is a bare title/label. If instead the line reads like a fresh command, we
# abandon the pending intent and classify it normally. Kept deliberately small
# and deterministic — no extra model call.
_NEW_COMMAND_HINTS = (
    "schedule", "book", "create", "invite", "add ", "make ", "grant",
    "list", "show", "what", "help",
)


def _looks_like_new_command(text: str) -> bool:
    t = text.strip().lower()
    return any(t.startswith(h) for h in _NEW_COMMAND_HINTS)


def handle(text: str, history: list[dict], api, loop, classifier, pending=None):
    """One turn: classify -> resolve -> run gated loop -> report.

    `pending` is a half-built Intent carried across turns (or None). Returns the
    pending intent to carry into the next turn.
    """
    # If we're mid-request, treat this line as the answer to the missing slot —
    # UNLESS it reads like a brand-new command, in which case start over.
    intent = None
    if pending is not None and not _looks_like_new_command(text):
        slot = getattr(pending, "_pending_slot", None)
        if slot:
            candidate_slots = dict(pending.slots)
            candidate_slots[slot] = text.strip()
            pending.slots = candidate_slots
            intent = pending
    if intent is None:
        try:
            intent = classifier.classify(text, history)
        except ClassifierError as err:
            print(f"[classifier error] {err}")
            return None

    if intent.action == "help":
        print("I can: schedule a session, invite attendees, add a member, or list events.")
        print("e.g. 'schedule a 45-minute design review next Tuesday at 9am'")
        return None
    if intent.action == "unknown":
        print("I didn't understand that. Try: 'schedule a 45-minute design review "
              "next Tuesday at 9am' or 'list my events'.")
        return None
    if intent.action in {"list_events", "list_sessions"}:
        try:
            _render_reads(api, intent)
        except NeedsSlot as err:
            # No/ambiguous event for list_sessions -> ask, and carry it so the
            # next line ("Event 3") merges into this intent rather than being
            # re-classified from scratch.
            intent._pending_slot = err.slot
            _ask_for_slot(err)
            return intent
        except SlotError as err:
            print(f"I need a bit more detail: {err}")
        return None

    # Resolve deterministically (may raise -> ask the user).
    try:
        if hasattr(intent, "_pending_slot"):
            del intent._pending_slot
        plans = intent_to_plan(api, intent)
    except NeedsSlot as err:
        # Remember what we have so far; ask for just the missing slot.
        intent._pending_slot = err.slot
        _ask_for_slot(err)
        return intent
    except SlotError as err:
        print(f"I need a bit more detail: {err}")
        return None
    except ValueError as err:
        print(f"I couldn't resolve that: {err}")
        return None

    result = loop.run(plans)
    print(result["trace"])

    # Surface anything the loop flagged as needing the user's decision — the
    # trace may *say* "ask the user" but the trace alone never actually asks.
    for note in result.get("attention", []):
        print(f"\n{note}")

    if result["status"] == "budget_exhausted":
        print(f"\n[stopped: budget exhausted] completed={result['completed']} "
              f"skipped={result['skipped']}")
    elif result["skipped"]:
        if not result.get("attention"):
            print(f"\n[done] completed={result['completed']} skipped={result['skipped']}")
    else:
        print(f"\n[done] completed={result['completed']}")
    return None


def repl() -> None:
    api, loop, classifier = build_components()
    print("Event agent (OpenAI). Type a request (type 'exit' or Ctrl-D to quit).")
    print("e.g. 'schedule a 45-minute design review next Tuesday at 9am'\n")
    history: list[dict] = []
    pending = None
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if text.lower() in {"exit", "quit"}:
            print("Goodbye.")
            break
        pending = handle(text, history, api, loop, classifier, pending=pending)
        history.append({"role": "user", "content": text})
        print()


def main() -> None:
    args = sys.argv[1:]
    if args:
        # one-shot mode: python -m agent.chat "..."
        api, loop, classifier = build_components()
        handle(" ".join(args), [], api, loop, classifier)
    else:
        repl()


if __name__ == "__main__":
    main()
