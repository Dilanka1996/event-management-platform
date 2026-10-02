# Tradeoffs

## Which track, and why
**Track: the gated agent track** — build an agent that drives the platform over
the public API, with a human in the loop, and make the *safety* properties
provable.

I chose it because the interesting, gradeable part of this assignment is not
"call an endpoint" — it's the nine behavioral requirements (gate outside the
model, preview whole, bounded + honest, interruptible, survives hostile data).
Those are *system* properties, and they're where a naive LLM-agent design falls
over. So I optimised for a design where those properties are **structural**
(code the model can't reach) rather than **promptual** (hoping the model
behaves).

The single biggest track decision inside that: **the LLM understands; code
resolves and executes.** We seriously evaluated letting LangChain own the loop,
audited it against the nine requirements, and found it structurally missing
five — including the one that matters most ("a gate the model can't talk its
way past"). So the LLM was demoted to the *understanding* layer, and the gated
loop stayed ours. See `docs/adr/0001`.

## What I cut
- **LangChain / a framework agent.** Cut deliberately after the audit. It would
  have bought tool-calling ergonomics we didn't need and cost us the gate
  guarantee. (`docs/adr/0003`)
- **Whole-plan atomic preview** (requirement "multi-write previewed whole").
  The current loop previews-and-commits **per write**; a true "preview all
  changes before any land" phase across a multi-step plan is not implemented. I
  know exactly where it goes (a preview phase between resolve and commit in
  `AgentLoop`) but left it out to keep the change surface small.
- **Rich multi-intent planning.** The classifier identifies one action per
  turn; compound requests ("schedule X *and* invite Y") aren't decomposed into
  an ordered multi-plan batch yet.
- **The deterministic date grammar's long tail** ("the second Tuesday of next
  month", "EOD"). `parse_when` covers ISO, relative days, weekday names, and
  clock times — the common cases — and asks the user otherwise rather than
  guessing.
- **A bigger/more reliable model.** `llama3.2:3b` over `llama3.1:8b` for
  footprint; over `1b` for structured-output reliability.

## Decisions this track forced
- **Gate placement** → outside the model, in our loop (`docs/adr/0001`).
- **Trust boundary for slots** → LLM emits hints only; `event_id`, UTC, and room
  are resolved deterministically; LLM output is treated as untrusted input
  (`docs/adr/0002`).
- **Model/runtime** → local Ollama, no framework, no hosted API
  (`docs/adr/0003`).
- **Eval determinism** → keep a deterministic `make test` (no LLM); put the
  real-model tests behind `make test-llm`, skipped when Ollama is absent.
- **Infra coupling** → do **not** make the backend container depend on the
  Ollama container (a ~3.7 GB image); chat starts Ollama explicitly. (This was
  a course-correction after a real misstep — see `AI-WORKFLOW.md`.)

## What two more weeks would buy
1. **True whole-plan preview & commit** — a two-phase plan (preview every write,
   one approval of the full diff, then commit all), satisfying the "move the
   keynote and shift everything after it" requirement properly.
2. **Multi-intent decomposition** — the LLM returns an ordered list of intents;
   the resolver builds a `Plan` batch; the loop previews the batch.
3. **A stronger, measurable understanding layer** — either a fine-tuned small
   classifier or an embedding-intent-router + deterministic slots, with a real
   labeled eval set and a published accuracy number (today the LLM tests are a
   pass-rate threshold, not a crisp metric).
4. **Concurrency/idempotency hardening** — the loop is single-threaded; add
   idempotency keys and re-check-on-conflict so retries and simultaneous writers
   can't double-book a room.
5. **Richer interruption** — today `interrupt()` absorbs a "use Room B" note at
   a safe point; generalize it to arbitrary mid-plan corrections with replanning.
6. **A front-end** — the REPL is a prove-the-pipeline shell; a small UI (or a
   streamed trace) would show legibility off properly.
