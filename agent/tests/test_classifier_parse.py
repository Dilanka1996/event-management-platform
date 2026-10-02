"""Deterministic tests for the classifier's parsing/fallback (no real LLM).

We inject a fake in-process `llm` object so the JSON handling, schema coercion,
and degradation-to-unknown are tested without loading the model.
"""

from agent.classifier import Intent, IntentClassifier


class _FakeLlama:
    """Minimal stand-in for a llama_cpp.Llama returning canned content."""

    def __init__(self, content):
        self._content = content

    def create_chat_completion(self, **kwargs):
        return {"choices": [{"message": {"content": self._content}}]}


def _classifier_returning(content):
    return IntentClassifier(llm=_FakeLlama(content))


def test_parses_valid_json():
    c = _classifier_returning(
        '{"action":"invite","confidence":0.9,"slots":{"emails":"a@b.com"}}'
    )
    intent = c.classify("invite a@b.com")
    assert intent.action == "invite"
    assert intent.slots["emails"] == "a@b.com"
    assert intent.confidence == 0.9


def test_bad_json_degrades_to_unknown():
    c = _classifier_returning("Sure! Here's the JSON: ...")
    intent = c.classify("do something")
    assert intent.action == "unknown"


def test_unknown_action_string_is_coerced():
    c = _classifier_returning('{"action":"delete_everything","confidence":0.9}')
    assert c.classify("x").action == "unknown"


def test_slots_must_be_dict():
    c = _classifier_returning('{"action":"help","confidence":0.5,"slots":"nope"}')
    assert c.classify("help").slots == {}


def test_intent_from_json_defaults():
    intent = Intent.from_json({"action": "help"})
    assert intent.action == "help"
    assert intent.slots == {}
    assert intent.confidence == 0.0
