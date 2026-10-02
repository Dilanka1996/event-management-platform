"""Deterministic tests for the classifier's parsing/fallback (no real LLM).

We inject a fake `post` transport so the JSON handling, schema coercion, and
degradation-to-unknown are tested without Ollama.
"""

from agent.classifier import Intent, OllamaClassifier


def _fake_post_returning(content):
    def _post(path, payload):
        assert path == "/api/chat"
        return {"message": {"content": content}}
    return _post


def test_parses_valid_json():
    c = OllamaClassifier(post=_fake_post_returning(
        '{"action":"invite","confidence":0.9,"slots":{"emails":"a@b.com"}}'
    ))
    intent = c.classify("invite a@b.com")
    assert intent.action == "invite"
    assert intent.slots["emails"] == "a@b.com"
    assert intent.confidence == 0.9


def test_bad_json_degrades_to_unknown():
    c = OllamaClassifier(post=_fake_post_returning("Sure! Here's the JSON: ..."))
    intent = c.classify("do something")
    assert intent.action == "unknown"


def test_unknown_action_string_is_coerced():
    c = OllamaClassifier(post=_fake_post_returning(
        '{"action":"delete_everything","confidence":0.9}'
    ))
    assert c.classify("x").action == "unknown"


def test_slots_must_be_dict():
    c = OllamaClassifier(post=_fake_post_returning(
        '{"action":"help","confidence":0.5,"slots":"nope"}'
    ))
    assert c.classify("help").slots == {}


def test_intent_from_json_defaults():
    intent = Intent.from_json({"action": "help"})
    assert intent.action == "help"
    assert intent.slots == {}
    assert intent.confidence == 0.0
