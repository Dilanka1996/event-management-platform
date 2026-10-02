"""Text interface for the event-management agent.

Usage:
    python -m agent.main            # interactive REPL (delegates to agent.chat)
    python -m agent.main --demo     # run the built-in scenarios

Auth: reads EMP_TOKEN (default: tok_1, the seeded ADMIN user) and EMP_BASE_URL
(default: http://localhost:8000). It talks to the platform only through the
public API, with no elevated key.
"""

from __future__ import annotations

import sys


def repl() -> None:
    # The real NL front-end lives in agent.chat (Ollama classification +
    # deterministic resolution + the gated loop).
    from agent.chat import repl as chat_repl

    chat_repl()


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