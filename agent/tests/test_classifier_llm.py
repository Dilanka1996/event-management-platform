"""LLM-backed intent classification tests against a REAL local Ollama model.

Run via `make test-llm` (requires `make ollama-pull` first). These tests hit
Ollama at OLLAMA_BASE_URL with OLLAMA_MODEL (default llama3.2:3b) and assert on
the STRUCTURED payload, not prose. Because a real model is stochastic, we accept
a pass-rate threshold rather than demanding every case.

If Ollama is unreachable, the whole module is skipped so `pytest` on a bare
machine doesn't fail spuriously.
"""

from __future__ import annotations

import os

import httpx
import pytest

from agent.classifier import OllamaClassifier

BASE = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")


def _ollama_up() -> bool:
    try:
        return httpx.get(f"{BASE}/api/tags", timeout=2.0).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _ollama_up(), reason=f"Ollama not reachable at {BASE}")


@pytest.fixture(scope="module")
def classifier():
    return OllamaClassifier(BASE, MODEL)


# (utterance, expected action, slots that must be present)
CASES = [
    ("Schedule a 45-minute design review next Tuesday at 9 am in whichever room is free",
     "create_session", {"title", "when", "duration"}),
    ("book a 30 minute standup tomorrow at 10am", "create_session", {"when", "duration"}),
    ("invite alice@example.com and bob@example.com to Event 3", "invite", {"emails"}),
    ("make carol@example.com a contributor on Event 1", "add_member", {"emails", "role"}),
    ("what events do I have?", "list_events", set()),
    ("tell me a joke about cricket", "unknown", set()),
]


def test_intent_classification_pass_rate(classifier):
    passed = 0
    failures = []
    for text, want_action, want_slots in CASES:
        intent = classifier.classify(text)
        ok = intent.action == want_action and want_slots.issubset(set(intent.slots))
        if ok:
            passed += 1
        else:
            failures.append(f"{text!r} -> action={intent.action} slots={intent.slots}")
    rate = passed / len(CASES)
    assert rate >= 0.8, (
        f"intent pass rate {rate:.0%} ({passed}/{len(CASES)})\n"
        + "\n".join(failures)
    )


def test_classifier_never_returns_event_id_or_utc():
    """The model must not invent resolved values — only raw hints."""
    intent = classifier.classify(
        "schedule a 45-minute design review next Tuesday at 9am on Event 3"
    )
    slots = intent.slots
    assert "event_id" not in slots
    for key in ("start", "end"):
        assert key not in slots
