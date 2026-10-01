"""Legible, replayable trace of an agent session.

Every tool call and its raw response is recorded here, in order, so the user
can reconstruct the session afterward without reading server logs. This is the
same structure the eval harness asserts against (call sequence, not just final
state).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Step:
    kind: str  # "think" | "call" | "result" | "gate" | "interrupt" | "stop"
    text: str
    data: dict | None = None


@dataclass
class Trace:
    steps: list[Step] = field(default_factory=list)

    def add(self, kind: str, text: str, data: dict | None = None) -> Step:
        step = Step(kind=kind, text=text, data=data)
        self.steps.append(step)
        return step

    def calls(self) -> list[tuple[str, str]]:
        """The (method, path) sequence — what evals assert on."""
        out = []
        for s in self.steps:
            if s.kind == "call" and s.data:
                out.append((s.data.get("method"), s.data.get("path")))
        return out

    def render(self) -> str:
        lines = []
        for s in self.steps:
            prefix = {
                "think": "🤔",
                "call": "→",
                "result": "←",
                "gate": "⛔",
                "interrupt": "⏸",
                "stop": "■",
            }.get(s.kind, " ")
            lines.append(f"{prefix} {s.text}")
        return "\n".join(lines)
