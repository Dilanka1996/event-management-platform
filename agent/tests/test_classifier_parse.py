"""Deterministic tests for the classifier's parsing/fallback (no network, no key).

We inject a fake OpenAI-shaped client (with the `.chat.completions.create(...)`
surface the real SDK exposes) so the JSON handling, schema coercion, and
degradation-to-unknown are tested without calling a real model.
"""

import pytest

from agent.classifier import ClassifierError, Intent, IntentClassifier


# -- fake OpenAI client ------------------------------------------------------


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeChatCompletions:
    def __init__(self, owner):
        self._owner = owner

    def create(self, **kwargs):
        self._owner.calls.append(kwargs)
        return type("_Resp", (), {"choices": [_FakeChoice(self._owner.content)]})()


class _FakeOpenAIClient:
    """Minimal stand-in for openai.OpenAI."""

    def __init__(self, content):
        self.content = content
        self.calls = []
        self.chat = type("_Chat", (), {"completions": _FakeChatCompletions(self)})()


def _classifier_returning(content):
    return IntentClassifier(client=_FakeOpenAIClient(content))


# -- parsing / fallback ------------------------------------------------------


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


# -- OpenAI call shape -------------------------------------------------------


def test_uses_strict_json_schema():
    c = _classifier_returning('{"action":"help","confidence":0.5}')
    c.classify("help")
    call = c._client.calls[0]
    assert call["model"] == "gpt-4o-mini"
    rf = call["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    schema = rf["json_schema"]["schema"]
    # Strict mode: additionalProperties false + every property in `required`.
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["action", "confidence", "slots"]
    assert schema["properties"]["slots"]["additionalProperties"] is False
    # Slot keys are required but nullable (model returns null for absent ones).
    assert schema["properties"]["slots"]["properties"]["title"]["type"] == [
        "string",
        "null",
    ]


def test_null_slots_are_dropped():
    c = _classifier_returning(
        '{"action":"create_session","confidence":0.9,"slots":'
        '{"title":"Design Review","event":null,"when":null,"duration":null,'
        '"room":null,"emails":null,"role":null}}'
    )
    intent = c.classify("schedule a design review")
    assert intent.slots == {"title": "Design Review"}


def test_parses_structured_output():
    c = _classifier_returning(
        '{"action":"create_session","confidence":0.95,'
        '"slots":{"title":"Design Review","when":"next Tuesday at 9am"}}'
    )
    intent = c.classify("schedule a design review next Tuesday at 9am")
    assert intent.action == "create_session"
    assert intent.slots["title"] == "Design Review"


def test_client_requires_api_key_when_not_injected(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    c = IntentClassifier()
    with pytest.raises(ClassifierError):
        c.classify("list my events")
