"""LLM-backed intent classification tests against the REAL in-process model.

Run via `make test-llm`. These load the Qwen2.5 GGUF in-process via
llama-cpp-python (see agent/classifier.py) and assert on the STRUCTURED payload,
not prose. Because a real model is stochastic, we accept a pass-rate threshold
rather than demanding every case.

If llama-cpp-python or the model can't be loaded, the whole module is skipped so
`pytest` on a bare machine doesn't fail spuriously.
"""

from __future__ import annotations

import pytest

from agent.classifier import ClassifierError, IntentClassifier

# Load the model ONCE for the whole module and reuse the instance everywhere —
# both for the availability gate and for the tests — so the ~1GB weights are
# read from disk a single time.
_CLASSIFIER = IntentClassifier()
_LOAD_ERROR: Exception | None = None
try:
    _CLASSIFIER._ensure_loaded()
except (ClassifierError, ImportError) as _err:  # pragma: no cover - env dependent
    _LOAD_ERROR = _err


pytestmark = pytest.mark.skipif(
    _LOAD_ERROR is not None,
    reason=f"llama-cpp-python / model not available: {_LOAD_ERROR}",
)


@pytest.fixture(scope="module")
def classifier():
    return _CLASSIFIER


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


def test_classifier_never_returns_event_id_or_utc(classifier):
    """The model must not invent resolved values — only raw hints."""
    intent = classifier.classify(
        "schedule a 45-minute design review next Tuesday at 9am on Event 3"
    )
    slots = intent.slots
    assert "event_id" not in slots
    for key in ("start", "end"):
        assert key not in slots
