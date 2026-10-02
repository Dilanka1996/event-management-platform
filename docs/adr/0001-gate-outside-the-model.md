# ADR 0001 — The approval gate lives outside the model

## Status
Accepted

## Context
The assignment requires that writes "need approval," that "an instruction in
the system prompt is not a gate," and that the gate "must live somewhere the
model can't talk its way past." We considered building the agent on LangChain
(LangChain's `AgentExecutor` / tool-calling agent) because the brief mentioned
"an actual LLM with LangChain," and a framework agent gives you the
reason→act→observe loop for free.

The question that decided the architecture: **who owns control flow — the
model, or our code?**

## Decision
The gate (and the whole execution path: preview → gate → commit → trace →
budget → interrupt) lives in our own code (`agent/loop.py` + `agent/gate.py`),
**outside the model**. The LLM's only output is a structured `Intent`; it never
holds a commit-capable tool. Our `AgentLoop` executes the resolved `Plan`s.

## Rejected alternative
**Let a stock LangChain agent own execution, with the gate inside the tool
body.** It is genuinely simpler and "more LangChain."

Rejected because a stock agent satisfies only ~2 of the 9 stated requirements
out of the box. Concretely:

| Requirement | Stock LangChain agent |
|---|---|
| Gate the model can't bypass | ✗ gate can only live in the prompt (not a gate) or in a tool the **model chose to call** |
| Denial is a normal path (no retry) | ✗ default ReAct retries the same tool on error |
| Multi-write previewed whole | ✗ commits per tool call; no whole-plan preview phase |
| Interruptible mid-execution | ✗ no interruption mechanism |
| Bounded + honest "what completed" | ⚠ `max_iterations` stops, but reports no record of what landed |

Those four gaps are **architectural**, not prompt-tweakable. The only way to
place a gate the model cannot steer is to take control flow away from the
model — which is, by definition, a coordinator (the loop).

## Why
- A *gate* is defined by unavailability of an ungated path. A prompt is advice;
  a tool body is a path the model selects. Only a runtime coordinator makes the
  ungated path not exist.
- It keeps a clean trust boundary: untrusted NL/LLM output on one side; the
  structured, validated `Plan` and the six execution guarantees on the other.
- The codebase already anticipated this: `agent/planner.py`'s original docstring
  reserved a `plan()` seam for "a real LLM backend … but the approval gate and
  budget live in the loop, not the model."

## Consequences
- We keep `loop.py`/`gate.py` rather than delete them; the LLM is plugged in as
  the *understanding* layer that feeds the loop.
- We own retry/interrupt/budget/report semantics ourselves (more code), in
  exchange for provable guarantees and deterministic evals.
