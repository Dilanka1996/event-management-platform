# ADR 0004 — In-process LLM (llama-cpp-python) instead of an Ollama server

## Status
Accepted. Supersedes [ADR 0003](0003-local-ollama-over-hosted-api.md) *on the
runtime only* (the "local model, no framework, no hosted API" decision stands).

## Context
ADR 0003 chose a local model called **over HTTP from a running `ollama serve`**.
In practice the "server" part carried more weight than the model:

- `ollama serve` had to run somewhere — natively on the host
  (`host.docker.internal:11434`), as its own compose service (a ~3.6–3.7 GB
  image bundling GPU runtimes), or co-located in the backend image (a non-Python
  binary + an entrypoint supervisor + a model volume).
- Every one of those is *additional infrastructure* whose only job is to answer
  `/api/chat` for a process that is right there in the same repo.
- The classifier's actual dependency is narrow: **schema-constrained JSON out of
  a small instruct model**. It does not need a general model-serving daemon.

## Decision
Load the GGUF **in-process** with **`llama-cpp-python`** — default
`Qwen/Qwen2.5-1.5B-Instruct-GGUF` (`q4_k_m`, ~1 GB). The classifier calls
`llama.create_chat_completion(...)` directly; there is **no server and no model
port**. Output stays grammar-constrained via
`response_format={"type": "json_object", "schema": INTENT_SCHEMA}` (llama.cpp's
GBNF), equivalent to Ollama's `format=INTENT_SCHEMA`.

## Rejected alternatives
- **Keep the Ollama server** (native, sidecar, or co-located): rejected as
  strictly more moving parts — a separate process to install, start, health-wait
  and persist a model volume for, all to serve a request from the same codebase.
- **Hosted API / LangChain:** still rejected (see ADR 0001 & 0003).
- **A 0.5B model** (`Qwen2.5-0.5B-Instruct`): rejected for quality — 7-action
  routing + slot extraction with a long rules prompt is too much for 0.5B;
  `1.5B` is the size/quality sweet spot (and still ~1 GB vs. `3b`'s ~2 GB).

## Why
- **Fewer moving parts:** one Python process, one image layer, no supervisor, no
  network hop, no port. `docker compose` has one fewer service.
- **Still local, offline, secret-free, reproducible:** `temperature=0` + grammar
  constraints; `make test` never loads the model, `make test-llm` targets it.
- **Same trust boundary:** the classifier still only sees the user's utterance
  and still degrades to `action="unknown"` on any failure.
- **Smaller than before:** ~1 GB model baked into the image (vs. ~2 GB model +
  multi-GB server image) — the footprint went *down*.

## Consequences
- New dependency: `llama-cpp-python`. Installed from the prebuilt **CPU wheel
  index** to avoid a slow source build; on Apple-Silicon Docker this runs
  CPU-only (no GPU passthrough), which is fine for a 1.5B classifier.
- The GGUF is pre-downloaded into the image layer **and** cached in an
  `hf_cache` volume, so it is not re-fetched on each start/rebuild.
- `Llama` is **not thread-safe**: calls are serialised with a lock on the
  classifier instance, since uvicorn's request pool shares it.
- Renamed the class `OllamaClassifier` → `IntentClassifier` (no server to name
  after). Deterministic parse tests inject a fake `llm`, not a fake HTTP client.
