"""Interactive chat over the event-management API.

Pipeline (L1 design):
    text
      -> agent.classifier   (Ollama LLM: understanding + slot extraction)
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
    OLLAMA_BASE_URL  default http://localhost:11434
    OLLAMA_MODEL     default llama3.2:3b
"""

from __future__ import annotations

import os
import sys

from agent.classifier import ClassifierError, OllamaClassifier
from agent.gate import ApprovalGate
from agent.loop import AgentLoop
from agent.planner import intent_to_plan
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
    classifier = OllamaClassifier()
    return api, loop, classifier


def _render_reads(api: PlatformApi, action: str) -> None:
    """Read-only actions are rendered directly (no gate needed)."""
    if action == "list_events":
        events = api.list_events()
        if not events:
            print("(no events)")
        for e in events:
            print(f"  #{e['id']}  {e['title']}  [{e['timezone']}]")
    elif action == "list_sessions":
        # needs an event; ask via the resolver path elsewhere
        print("(specify an event, e.g. 'show sessions for Event 3')")


def handle(text: str, history: list[dict], api, loop, classifier) -> None:
    """One turn: classify -> resolve -> run gated loop -> report."""
    try:
        intent = classifier.classify(text, history)
    except ClassifierError as err:
        print(f"[classifier error] {err}")
        return

    if intent.action == "help":
        print("I can: schedule a session, invite attendees, add a member, or list events.")
        print("e.g. 'schedule a 45-minute design review next Tuesday at 9am'")
        return
    if intent.action == "unknown":
        print("I didn't understand that. Try: 'schedule a 45-minute design review "
              "next Tuesday at 9am' or 'list my events'.")
        return
    if intent.action in {"list_events", "list_sessions"}:
        _render_reads(api, intent.action)
        return

    # Resolve deterministically (may raise -> ask the user).
    try:
        plans = intent_to_plan(api, intent)
    except SlotError as err:
        print(f"I need a bit more detail: {err}")
        return
    except ValueError as err:
        print(f"I couldn't resolve that: {err}")
        return

    result = loop.run(plans)
    print(result["trace"])
    if result["status"] == "budget_exhausted":
        print(f"\n[stopped: budget exhausted] completed={result['completed']} "
              f"skipped={result['skipped']}")
    elif result["skipped"]:
        print(f"\n[done] completed={result['completed']} skipped={result['skipped']}")
    else:
        print(f"\n[done] completed={result['completed']}")


def repl() -> None:
    api, loop, classifier = build_components()
    print("Event agent (local LLM). Type a request (Ctrl-D to exit).")
    print("e.g. 'schedule a 45-minute design review next Tuesday at 9am'\n")
    history: list[dict] = []
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        handle(text, history, api, loop, classifier)
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
