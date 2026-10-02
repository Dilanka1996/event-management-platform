"""Intent classification via an IN-PROCESS local LLM (L1 design).

The LLM's ONLY job is understanding: turn a natural-language utterance into a
structured `Intent` (which action, and raw slot values). It does NOT resolve
event ids, UTC timestamps, or pick rooms — those are validated and resolved
deterministically in `slot_validation.py` / `planner.py`, then executed by the
gated `AgentLoop`.

Trust model: the returned `Intent` is UNTRUSTED input, exactly like a request
body. The classifier never sees event data (no injection surface from stored
text), and any parse failure degrades to `action="unknown"` so the chat layer
asks the user instead of guessing.

The model (default Qwen2.5-1.5B-Instruct, q4_k_m GGUF) is loaded once into this
process via llama-cpp-python. There is NO Ollama server and no model port —
inference runs in the same Python process as the API. Sampling is constrained by
a JSON-schema grammar (llama.cpp), so the result is always a valid payload
shape; correctness of the *values* is still the model's job.

Config (env):
    LLM_MODEL       default Qwen/Qwen2.5-1.5B-Instruct-GGUF
    LLM_MODEL_FILE  default qwen2.5-1.5b-instruct-q4_k_m.gguf
    LLM_N_CTX       default 4096  (context window)
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from typing import Literal

DEFAULT_REPO = "Qwen/Qwen2.5-1.5B-Instruct-GGUF"
DEFAULT_FILE = "qwen2.5-1.5b-instruct-q4_k_m.gguf"

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


# JSON schema that constrains decoding (llama.cpp grammar) to a valid payload
# shape. Note: llama.cpp's json_object/schema mode requires the top-level
# "properties" to be exhaustive, hence the explicit required list below.
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


class IntentClassifier:
    """In-process LLM classifier (llama-cpp-python). No resolution, no writes,
    no event data — it only turns an utterance into an `Intent`.

    The GGUF is loaded lazily on first use and cached on the instance. A single
    `Llama` object is NOT thread-safe, so calls are serialised with a lock; a
    FastAPI request pool would otherwise race on the same context.
    """

    def __init__(
        self,
        model: str | None = None,
        model_file: str | None = None,
        *,
        llm=None,
        n_ctx: int | None = None,
        verbose: bool = False,
    ):
        self.repo = model or os.getenv("LLM_MODEL", DEFAULT_REPO)
        self.filename = model_file or os.getenv("LLM_MODEL_FILE", DEFAULT_FILE)
        self.n_ctx = n_ctx or int(os.getenv("LLM_N_CTX", "4096"))
        self.verbose = verbose
        self._llm = llm  # injectable for tests
        self._lock = threading.Lock()

    def _ensure_loaded(self):
        """Load the GGUF once. Downloads from HF on first call if not cached."""
        if self._llm is not None:
            return self._llm
        try:
            from llama_cpp import Llama  # imported lazily so import-time is cheap
        except ImportError as err:  # pragma: no cover - depends on image
            raise ClassifierError(
                "llama-cpp-python is not installed; rebuild the image "
                "(see pyproject.toml / Dockerfile)."
            ) from err
        try:
            self._llm = Llama.from_pretrained(
                repo_id=self.repo,
                filename=self.filename,
                n_ctx=self.n_ctx,
                verbose=self.verbose,
            )
        except Exception as err:  # download / load failure
            raise ClassifierError(
                f"failed to load model {self.repo}/{self.filename}: {err}"
            ) from err
        return self._llm

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

        llm = self._ensure_loaded()
        try:
            # Grammar-constrained decoding: response_format pins output to
            # INTENT_SCHEMA, matching the old Ollama `format` behaviour.
            with self._lock:
                out = llm.create_chat_completion(
                    messages=messages,
                    response_format={"type": "json_object", "schema": INTENT_SCHEMA},
                    temperature=0,
                    max_tokens=256,
                )
        except Exception as err:
            raise ClassifierError(f"inference failed: {err}") from err

        content = ((out.get("choices") or [{}])[0].get("message") or {}).get("content", "")
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
