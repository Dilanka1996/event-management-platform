"""Intent classification via a local Ollama LLM (L1 design).

The LLM's ONLY job is understanding: turn a natural-language utterance into a
structured `Intent` (which action, and raw slot values). It does NOT resolve
event ids, UTC timestamps, or pick rooms — those are validated and resolved
deterministically in `slot_validation.py` / `planner.py`, then executed by the
gated `AgentLoop`.

Trust model: the returned `Intent` is UNTRUSTED input, exactly like a request
body. The classifier never sees event data (no injection surface from stored
text), and any parse failure degrades to `action="unknown"` so the chat layer
asks the user instead of guessing.

Config (env):
    OLLAMA_BASE_URL  default http://localhost:11434
    OLLAMA_MODEL     default llama3.2:3b
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Callable, Literal

import httpx

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
        try:
            confidence = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        return cls(action=action, slots=slots, confidence=confidence, raw=raw)


# JSON schema handed to Ollama's structured-output mode so sampling is
# constrained to a valid payload shape.
INTENT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": list(Action.__args__),  # type: ignore[attr-defined]
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "slots": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "event": {"type": "string"},
                "when": {"type": "string"},
                "duration": {"type": "string"},
                "room": {"type": "string"},
                # emails/role kept as strings here to stay schema-simple; the
                # validator normalises them (split / upper-case).
                "emails": {"type": "string"},
                "role": {"type": "string"},
            },
        },
    },
    "required": ["action", "confidence"],
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
- "event": the event the user names (e.g. "Event 3", "Hostile Data Demo"). Use
  a substring of the title; omit if the user names no event.
- "title": a short human title for a session (e.g. "Design Review").
- "when": the time phrase verbatim (e.g. "next Tuesday at 9am", "tomorrow
  3pm"). Do NOT convert to a date — leave it as words.
- "duration": the length phrase verbatim (e.g. "45-minute", "1 hour").
- "room": an explicit room name (e.g. "Room B"), or "any" if the user says
  "whichever room is free" / "any free room". Omit if unspecified.
- "emails": comma-separated email addresses as a single string.
- "role": one of ADMIN, CONTRIBUTOR, ATTENDEE (upper-case).

Examples:
User: "Schedule a 45-minute design review next Tuesday at 9 am in whichever
room is free"
{"action":"create_session","confidence":0.97,"slots":{"title":"Design Review",
"when":"next Tuesday at 9 am","duration":"45-minute","room":"any"}}

User: "invite alice@example.com and bob@example.com to Event 3"
{"action":"invite","confidence":0.96,"slots":{"event":"Event 3",
"emails":"alice@example.com, bob@example.com"}}

User: "make carol@example.com a contributor on Event 1"
{"action":"add_member","confidence":0.95,"slots":{"event":"Event 1",
"emails":"carol@example.com","role":"CONTRIBUTOR"}}

User: "what events do I have?"
{"action":"list_events","confidence":0.93,"slots":{}}

User: "tell me a joke"
{"action":"unknown","confidence":0.2,"slots":{}}

Return ONLY the JSON object."""


class ClassifierError(Exception):
    pass


class OllamaClassifier:
    """Talks to a local Ollama server. No resolution, no writes, no event data."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        *,
        post: Callable[[str, dict], dict] | None = None,
        timeout: float = 60.0,
    ):
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL", "llama3.2:3b")
        self._post = post or self._http_post
        self.timeout = timeout

    def _http_post(self, path: str, payload: dict) -> dict:
        try:
            resp = httpx.post(f"{self.base_url}{path}", json=payload, timeout=self.timeout)
        except httpx.HTTPError as err:  # network / connection issues
            raise ClassifierError(f"Ollama unreachable at {self.base_url}: {err}") from err
        if resp.status_code >= 400:
            raise ClassifierError(f"Ollama HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

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

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": INTENT_SCHEMA,
            "options": {"temperature": 0},
        }
        data = self._post("/api/chat", payload)
        content = (data.get("message") or {}).get("content", "")
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
