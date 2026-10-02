# ADR 0005 — Hosted OpenAI model instead of a local in-process model

## Status
Accepted. Supersedes [ADR 0004](0004-in-process-llama-cpp-over-ollama-server.md)
(and, transitively, [ADR 0003](0003-local-ollama-over-hosted-api.md) on the
*model/runtime* axis). The decisions that still stand from earlier ADRs:
[ADR 0001](0001-gate-outside-the-model.md) (gate outside the model) and
[ADR 0002](0002-llm-understanding-deterministic-resolution.md) (LLM understands;
code resolves). Only *which model, and how it's hosted* changed.

## Context
ADR 0004 loaded a ~1 GB `Qwen2.5-1.5B-Instruct` GGUF in-process via
`llama-cpp-python`. That kept everything offline and secret-free, but it carried
real weight:

- A ~1 GB model baked into the image layer **and** an `hf_cache` volume to avoid
  re-downloading it — a heavy image and a non-trivial first-build download.
- A large C-extension dependency (`llama-cpp-python`) installed from a bespoke
  CPU wheel index to dodge a slow source build (cmake/gcc).
- A serialisation lock on the classifier because a single `Llama` object is not
  thread-safe under uvicorn's request pool.
- The quality ceiling of a 1.5B model at 7-action routing + slot extraction with
  a long rules prompt — the weakest link in the understanding step.

We want the image light, the dependency surface small, and the comprehension
stronger, without moving the trust boundary or breaking `make test` on a clean
machine.

## Decision
Call the **hosted OpenAI Chat Completions API** (default `gpt-4o-mini`) directly
from the classifier, using **Structured Outputs**:

```python
response_format={"type": "json_schema",
                 "json_schema": {"name": "intent", "strict": True,
                                 "schema": INTENT_SCHEMA}}
```

- No model weights in the image, no `llama-cpp-python`, no `huggingface-hub`, no
  `hf_cache` volume, no thread-safety lock.
- `LLM_MODEL` selects the model (default `gpt-4o-mini`);
  `OPENAI_API_KEY` is required at runtime; `OPENAI_BASE_URL` allows an
  OpenAI-compatible endpoint.
- `make test` stays deterministic and key-free: the parser tests inject a fake
  OpenAI-shaped `client`, and the prompt is sent as the same `SYSTEM_PROMPT`.

## Rejected alternatives
- **Keep the local GGUF (ADR 0004):** rejected for image weight, dependency
  weight, and weaker slot extraction. The offline property was nice but is not a
  requirement here.
- **Local Ollama server (ADR 0003):** rejected — strictly more moving parts than
  even the in-process model.
- **LangChain / a framework agent:** still rejected (ADR 0001) — the gate lives
  in our loop and the model must not own control flow.

## Why
- **Much smaller, simpler image:** the Dockerfile is now just Python + Poetry +
  `libpq`/`curl`. No GGUF layer, no CPU-wheel index, no HF cache volume.
- **Stronger understanding:** `gpt-4o-mini` + strict JSON schema is materially
  better at multi-slot extraction than a 1.5B local model, with far less prompt
  gymnastics. Named-entity slots (`title`, `emails`, `role`) are the payoff.
- **Same trust boundary:** the classifier still sees only the user's utterance,
  still returns an untrusted `Intent` (hints only — never `event_id`/UTC/room),
  and still degrades to `action="unknown"` on any failure. The resolver
  re-validates every slot; the loop owns preview/gate/commit.
- **Deterministic tests preserved:** `make test` needs no key and no network.

## Consequences
- New runtime requirement: `OPENAI_API_KEY` (a secret). `make test` and the
  deterministic scenarios do **not** need it; `make test-llm` and `make chat` do.
- New runtime egress: the user's utterance is sent to OpenAI. Event data is
  never sent — the classifier has no access to it.
- The LLM-backed tests skip cleanly when `openai` or the key is absent, so a
  bare CI machine never fails on their account.
- `test_classifier_parse.py` now injects an OpenAI-shaped fake client instead of
  a fake `llama_cpp` object.
