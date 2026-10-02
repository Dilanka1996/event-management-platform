# ADR 0003 — Local Ollama model, no framework, no hosted API

## Status
Superseded by [ADR 0004](0004-in-process-llama-cpp-over-ollama-server.md).
(The *local model, no framework, no hosted API* decision still holds; only the
"Ollama server" runtime is replaced by in-process inference. See the note under
"Consequences".)

## Context
The agent needs an LLM for intent classification and slot extraction. The brief
originally pointed at "an actual LLM with LangChain." Choices were: a hosted API
(OpenAI/Anthropic), LangChain + a hosted model, or a **local model** (Ollama)
called directly.

Constraints that shaped it: the assignment rewards deterministic, replayable
evals; CI must run without secrets; the gate must not be influenced by a
framework that wants to own control flow; and we wanted no injection surface in
the understanding step.

## Decision
Call a **local Ollama model (`llama3.2:3b`) directly over HTTP** (via `httpx`),
with **no LangChain and no framework agent**. Use Ollama's JSON-schema
constrained output (`format=INTENT_SCHEMA`, `temperature=0`).

## Rejected alternatives
- **Hosted API (OpenAI/Anthropic):** rejected — needs a key/secret in CI, costs
  money, non-reproducible across runs, and sends user/event context to a third
  party.
- **LangChain agent + hosted or local model:** rejected on *control-flow*
  grounds (see ADR 0001) — the framework's premise ("the model drives the loop")
  conflicts with "a gate the model can't talk past." LangChain would have bought
  us tool-calling ergonomics we did not need once the loop stayed ours.
- **Bigger local model (`llama3.1:8b`):** rejected for footprint; `3b` was the
  reliability/size sweet spot for schema-constrained classification (1B was
  visibly weak at structured output).

## Why
- **Deterministic-ish and offline:** `temperature=0` + schema constraints; runs
  without secrets, so `make test` stays clean and `make test-llm` targets the
  real model separately.
- **No framework in the safety path:** the model is *just* an HTTP endpoint
  returning a JSON object. Nothing can reorder our preview/gate/commit.
- **No injection surface:** the classifier sees only the user's utterance.
- **`3b` fits the task:** intent + slot JSON with a schema is well within its
  ability; the heavy lifting (resolution) is deterministic anyway.

## Consequences
- New runtime dependency: a running Ollama server. Tests that need it are
  **skipped when it is unreachable**, so a bare CI machine does not fail.
- Model output is still untrusted and can be malformed → degrade to
  `action="unknown"`, and all slots are re-validated downstream.
- The Ollama *Docker image* is large (~3.7 GB) because it bundles GPU runtimes;
  the *model* is ~2 GB. We therefore did **not** make the backend container
  depend on the Ollama container, so `make test` never pays that cost.
