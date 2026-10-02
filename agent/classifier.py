"""Intent classification via a hosted OpenAI model (L1 design).

The LLM's ONLY job is understanding: turn a natural-language utterance into a
structured `Intent` (which action, and raw slot values). It does NOT resolve
event ids, UTC timestamps, or pick rooms — those are validated and resolved
deterministically in `slot_validation.py` / `planner.py`, then executed by the
gated `AgentLoop`.

Trust model: the returned `Intent` is UNTRUSTED input, exactly like a request
body. The classifier never sees event data (no injection surface from stored
text), and any parse failure degrades to `action="unknown"` so the chat layer
asks the user instead of guessing.

Backend: the hosted OpenAI Chat Completions API (default `gpt-4o-mini`) with
Structured Outputs (`response_format={"type":"json_schema",...}`), so the model
is grammar-constrained to a valid payload shape. Only comprehension quality is
outsourced to the model; the trust boundary and safety semantics below are ours.

Config (env):
    LLM_MODEL        default gpt-4o-mini
    OPENAI_API_KEY   required
    OPENAI_BASE_URL  optional (OpenAI-compatible endpoint)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Literal

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

# The closed action set the rest of the system understands. "unknown" is the
# explicit "I did not understand" signal — the chat layer asks, never guesses.
Action = Literal[
    "create_session",
    "invite",
    "add_member",
    "list_events",
    "list_sessions",
    "help",
    "unknown",
]

VAGUE_SLOTS = {"title", "when", "room", "duration", "emails", "role", "event"}


@dataclass
class Intent:
    """Structured, UNRESOLVED understanding of one user request.

    `slots` holds raw values/hints (e.g. title="Design Review",
    when="next Tuesday at 9am", emails=["a@b.com"]). It must never carry a
    resolved event_id or a UTC timestamp — those come from the deterministic
    resolver.
    """

    action: Action
    slots: dict = field(default_factory=dict)
    confidence: float = 0.0
    raw: str = ""

    @classmethod
    def from_json(cls, data: dict, raw: str = "") -> "Intent":
        action = data.get("action", "unknown")
        if action not in Action.__args__:  # type: ignore[attr-defined]
            action = "unknown"
        slots = data.get("slots") or {}
        if not isinstance(slots, dict):
            slots = {}
        # Structured Outputs forces every slot key to be present; the model
        # signals "not provided" with null. Drop those so callers only see the
        # slots the user actually gave us.
        slots = {k: v for k, v in slots.items() if v is not None}
        try:
            confidence = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        return cls(action=action, slots=slots, confidence=confidence, raw=raw)


# JSON schema for OpenAI Structured Outputs. Strict mode requires, at every
# level: `additionalProperties: false`, and `required` listing EVERY property.
# To still let the model omit a slot, each slot is typed nullable and the model
# returns null for "not provided"; `Intent.from_json` drops the nulls.
INTENT_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {
            "type": "string",
            "enum": list(Action.__args__),  # type: ignore[attr-defined]
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "slots": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": {"type": ["string", "null"]},
                "event": {"type": ["string", "null"]},
                "when": {"type": ["string", "null"]},
                "duration": {"type": ["string", "null"]},
                "room": {"type": ["string", "null"]},
                # emails/role kept as strings here to stay schema-simple; the
                # validator normalises them (split / upper-case).
                "emails": {"type": ["string", "null"]},
                "role": {"type": ["string", "null"]},
            },
            "required": [
                "title", "event", "when", "duration", "room", "emails", "role",
            ],
        },
    },
    "required": ["action", "confidence", "slots"],
}

SYSTEM_PROMPT = """You are the intent classifier for an event-management agent.

You ONLY understand the user's request. You do NOT execute anything, resolve
IDs, compute dates, or choose rooms — other deterministic components do that.

Return a JSON object: {"action": <one of the actions>, "confidence": <0..1>,
"slots": {...}}.

Actions and when to use them:
- "create_session": the user wants to schedule/book a session or meeting in a
  room (e.g. "schedule a 45-minute design review next Tuesday at 9am").
- "invite": the user wants to invite people by email to an event.
- "add_member": the user wants to grant a role (ADMIN|CONTRIBUTOR|ATTENDEE) to
  a person on an event.
- "list_events": list the events the user can access.
- "list_sessions": list sessions for an event.
- "help": the user asks what you can do.
- "unknown": the request is unclear, off-topic, or matches no action.

Slot extraction (use the user's own words; do NOT invent values):
Always include every slot key in "slots". Use null for any slot the user did
NOT provide — never guess or invent one.
- "event": the event the user names (e.g. "Event 3", "Hostile Data Demo"). Use
  a substring of the title; null if the user names no event.
- "title": a short human title for a session (e.g. "Design Review").
- "when": the time phrase verbatim (e.g. "next Tuesday at 9am", "tomorrow
  3pm"). Do NOT convert to a date — leave it as words.
- "duration": the length phrase verbatim (e.g. "45-minute", "1 hour").
- "room": an explicit room name (e.g. "Room B"), or "any" if the user says
  "whichever room is free" / "any free room". null if unspecified.
- "emails": comma-separated email addresses as a single string.
- "role": one of ADMIN, CONTRIBUTOR, ATTENDEE (upper-case).

Examples:
User: "Schedule a 45-minute design review next Tuesday at 9 am in whichever
room is free"
{"action":"create_session","confidence":0.97,"slots":{"title":"Design Review",
"event":null,"when":"next Tuesday at 9 am","duration":"45-minute","room":"any",
"emails":null,"role":null}}

User: "invite alice@example.com and bob@example.com to Event 3"
{"action":"invite","confidence":0.96,"slots":{"event":"Event 3",
"emails":"alice@example.com, bob@example.com","title":null,"when":null,
"duration":null,"room":null,"role":null}}

User: "make carol@example.com a contributor on Event 1"
{"action":"add_member","confidence":0.95,"slots":{"event":"Event 1",
"emails":"carol@example.com","role":"CONTRIBUTOR","title":null,"when":null,
"duration":null,"room":null}}

User: "what events do I have?"
{"action":"list_events","confidence":0.93,"slots":{"title":null,"event":null,
"when":null,"duration":null,"room":null,"emails":null,"role":null}}

User: "tell me a joke"
{"action":"unknown","confidence":0.2,"slots":{"title":null,"event":null,
"when":null,"duration":null,"room":null,"emails":null,"role":null}}

Return ONLY the JSON object."""


class ClassifierError(Exception):
    pass


class IntentClassifier:
    """OpenAI-backed classifier. No resolution, no writes, no event data — it
    only turns an utterance into an `Intent`.

    The `openai` client is built lazily on first use and cached on the instance.
    Pass `client=` to inject a fake (used by the parser tests) so they run with
    no network and no API key.
    """

    def __init__(
        self,
        model: str | None = None,
        *,
        client=None,
        timeout: float | None = None,
    ):
        self.model = (
            model or os.getenv("LLM_MODEL") or DEFAULT_OPENAI_MODEL
        )
        self.timeout = timeout or float(os.getenv("OPENAI_TIMEOUT", "30"))
        self._client = client  # injectable for tests

    def _ensure_client(self):
        """Create the OpenAI client once (lazily)."""
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI  # imported lazily so import-time is cheap
        except ImportError as err:
            raise ClassifierError(
                "the 'openai' package is not installed; add it to pyproject.toml "
                "and rebuild the image (or `poetry install`)."
            ) from err
        if not os.getenv("OPENAI_API_KEY"):
            raise ClassifierError(
                "OPENAI_API_KEY is not set; export it before using the classifier."
            )
        # The SDK reads OPENAI_BASE_URL straight from the environment, so an
        # empty value (compose injects "" when the var is undefined) makes it
        # build a scheme-less URL ("missing an 'http://' or 'https://' protocol")
        # instead of falling back to the default endpoint. Drop the var when it
        # is blank so the SDK uses https://api.openai.com/v1.
        base_url = (os.getenv("OPENAI_BASE_URL") or "").strip()
        if base_url:
            self._client = OpenAI(base_url=base_url, timeout=self.timeout)
        else:
            os.environ.pop("OPENAI_BASE_URL", None)
            self._client = OpenAI(timeout=self.timeout)
        return self._client

    def _complete(self, messages: list[dict]) -> str:
        client = self._ensure_client()
        try:
            # Structured Outputs: strict json_schema constrains decoding to the
            # INTENT_SCHEMA payload shape.
            out = client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "intent",
                        "strict": True,
                        "schema": INTENT_SCHEMA,
                    },
                },
                temperature=0,
                max_completion_tokens=256,
            )
        except Exception as err:
            raise ClassifierError(f"openai inference failed: {err}") from err
        if not out.choices:
            return ""
        return out.choices[0].message.content or ""

    # -- public API ----------------------------------------------------------

    def classify(self, text: str, history: list[dict] | None = None) -> Intent:
        """Return an `Intent` for `text`. Never raises on parse failure — it
        degrades to action="unknown" so the chat layer can ask the user."""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        # Keep only the user's utterance for classification. Untrusted stored
        # event text is never fed to the model.
        if history:
            for turn in history[-6:]:
                role = turn.get("role")
                if role in {"user", "assistant"}:
                    messages.append({"role": role, "content": str(turn.get("content", ""))})
        messages.append({"role": "user", "content": text})

        content = self._complete(messages)
        return self._parse(content, text)

    @staticmethod
    def _parse(content: str, raw: str) -> Intent:
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return Intent(action="unknown", slots={}, confidence=0.0, raw=raw)
        if not isinstance(data, dict):
            return Intent(action="unknown", slots={}, confidence=0.0, raw=raw)
        return Intent.from_json(data, raw)
