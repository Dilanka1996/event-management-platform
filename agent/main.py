"""Thin text interface for the event-management agent.

Usage:
    python -m agent.main            # interactive REPL
    python -m agent.main --demo     # run the built-in scenarios

Auth: reads EMP_TOKEN (default: tok_1, the seeded ADMIN user) and EMP_BASE_URL
(default: http://localhost:8000). It talks to the platform only through the
public API, with no elevated key.
"""

from __future__ import annotations

import os
import sys

from agent.gate import ApprovalGate
from agent.loop import AgentLoop
from agent.planner import plan_schedule_review
from agent.tools import PlatformApi


def _stdin_approval(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() in {"y", "yes"}
    except EOFError:
        return False


def build_agent(budget: int = 8) -> AgentLoop:
    base = os.getenv("EMP_BASE_URL", "http://localhost:8000")
    token = os.getenv("EMP_TOKEN", "tok_1")
    api = PlatformApi(base, token)
    return AgentLoop(api, ApprovalGate(_stdin_approval), budget=budget)


def repl() -> None:
    agent = build_agent()
    print("Event agent. Type a request (Ctrl-D to exit).")
    print("e.g. 'schedule a 45-minute design review next Tuesday at 9am'\n")
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue

        # Very thin NL front-end: maps a few scripted intents to plans.
        try:
            if "design review" in text.lower():
                plans = [
                    plan_schedule_review(
                        agent.api,
                        event_hint=os.getenv("EMP_EVENT", "Event 1"),
                        local_date_iso=os.getenv("EMP_DATE", "2025-03-11"),
                        local_time=os.getenv("EMP_TIME", "09:00"),
                    )
                ]
                result = agent.run(plans)
                print(result["trace"])
            else:
                print("(demo REPL only understands the design-review request;")
                print(" run `python -m agent.main --demo` for all scenarios)")
        except Exception as err:  # noqa: BLE001
            print(f"error: {err}")


def demo() -> None:
    from agent.scenarios import run_all

    run_all()


def main() -> None:
    if "--demo" in sys.argv:
        demo()
    else:
        repl()


if __name__ == "__main__":
    main()