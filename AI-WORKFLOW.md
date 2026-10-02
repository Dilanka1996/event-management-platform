# AI Workflow

How I used AI on this assignment: what I drove, what I delegated, how I planned,
and — most importantly — a specific case where the AI produced wrong code, how
I caught it, and what we changed.

## Tools used
- **A coding assistant (agent mode) in the editor** for: reading/refactoring the
  agent modules, writing the new `classifier.py` / `slot_validation.py` /
  `chat.py`, wiring Docker/Makefile, and drafting these docs.
- **A long design conversation with the assistant** as a *sounding board* for
  architecture — this is where most of the value was. I drove the requirements;
  the assistant helped me stress-test them (see "planning" below).
- **In-process `llama-cpp-python` (Qwen2.5-1.5B-Instruct, GGUF)** as the runtime
  LLM — loaded directly in the backend process, no model server. Not a code
  assistant.

## What I drove vs. delegated

| I drove (my decisions) | I delegated (assistant executed) |
|---|---|
| The architecture: *gate outside the model; the LLM only understands* | Writing the classifier/slot/planner/chat modules |
| Rejecting LangChain as the agent (after auditing the 9 requirements against it) | Producing the requirement-by-requirement audit that informed that call |
| Choosing L1 (LLM understanding) **with deterministic resolution** of the dangerous slots | The `parse_when` date grammar, email/role validators |
| Accepting/rejecting each Docker, lockfile, and dependency change | Compose/Makefile edits, test scaffolding |
| The decision that the model must never emit `event_id`/UTC/room | Enforcing it in code + tests |

Rules of engagement I kept: **the assistant proposes, I dispose.** Every
architectural claim the assistant made, I re-checked against the nine stated
requirements before acting on it.

## Planning process
1. **Read the real constraints first.** I had the assistant map the nine
   requirements onto the *actual* codebase (loop, gate, trace, scenarios)
   before proposing anything — not onto a generic "agent."
2. **Audit before commit.** When LangChain was on the table, I asked for a
   requirement-by-requirement verdict. It came back "2 supported, 5 not" — which
   is what changed my mind. I did not accept "LangChain is the assignment" as a
   reason to adopt it.
3. **Draw the trust boundary explicitly.** We separated *understanding* (LLM,
   untrusted) from *resolution + the six guarantees* (code, trusted), and named
   exactly which slots cross which way.
4. **Build bottom-up and test each layer** — deterministic tests with no LLM
   first, the real-model tests behind a separate `make test-llm`.
5. **Keep the eval suite honest** — the existing ~15 scenarios (the governor's
   guarantees) stayed intact and green while we changed the layer above them.

## The case where the AI produced wrong code

**What it did.** To make the agent work, the assistant set up **three different
ways to run the model** across the conversation, each as if it were the obvious
answer: first a separate `ollama` compose service; then (when I asked for
"single container") a *co-located* `ollama serve` bolted into the backend image
with a supervisord entrypoint; then finally the correct one — load a GGUF
**in-process** with `llama-cpp-python`. The first attempt also made `backend`
service `depends_on: ollama`.

**Why it was wrong.** Two separate problems:
1. The `depends_on: ollama` edge: `docker compose run backend …` (what
   `make test`, `make seed`, etc. use) honours `depends_on`, so **every**
   backend run tried to pull the `ollama/ollama` image — a **~3.6 GB** image
   (it bundles CUDA/ROCm runtimes). The fast deterministic test path got
   silently coupled to a heavyweight optional dependency.
2. Chasing "single container" led to *credential-stuffing Ollama into a Python
   image* — a non-Python binary + an entrypoint supervisor + a model volume,
   all so the app could keep talking to `localhost:11434`. That's strictly more
   moving parts than just running the model in the process that needs it.

**How I caught it.** I ran the deterministic tests and the command stalled on
`824f81b155e3 Downloading … 3.607GB`. I debugged step by step:
1. Read the captured output → the stall was an **image download**, not a test
   failure or a hanging container.
2. `docker compose ps` → no stuck container; the run was blocked on pull.
3. Reasoned from the compose semantics: `depends_on` → `run backend` pulls
   `ollama` → 3.6 GB. That traced straight back to the assistant's edit.
4. The "build Ollama into the backend image" attempt then failed differently —
   the installer exited on a missing `zstd` — which is a hint that I was forcing
   a server into a place it didn't belong.

**What I did.** Removed the whole server dependency:
- Deleted the `ollama` service *and* the `depends_on` edge.
- Dropped the co-located `ollama serve` idea entirely: the model now loads
  **in-process** via `llama-cpp-python` (Qwen2.5-1.5B GGUF). No port, no
  server, no entrypoint supervisor.
- `make test` never touches the model at all; `make test-llm` / `make chat` are
  the only paths that load it, and they cache it in the image/volume.

**The lesson.** The AI optimised for *local correctness* ("backend needs a
model") without reasoning about **blast radius** — who else triggers that edge —
or about whether the *transport* (a server on `localhost:11434`) was needed at
all. A dependency that is correct for `docker compose up` is wrong for
`docker compose run <service>` in a repo where the same service is invoked for
tests. And a "the obvious way to run a model is a server" assumption cost two
dead-end attempts before landing on the simpler in-process design. I now
sanity-check any infra edge the assistant adds against *every* command that
traverses it — and ask "does this need to be a separate process at all?"

**A second, smaller catch (same pattern, different layer).** The assistant wrote
`parse_when`, then wrote a test asserting that `"tomorrow at 9am"` from
`2025-03-08T00:00Z` resolves to `2025-03-09`. The test failed — and it was the
**test** that was wrong: `2025-03-08T00:00Z` is still `2025-03-07` in New York,
so "tomorrow" (resolved in the *event's* timezone) is `03-08`, not `03-09`. The
code was right; the AI's expectation anchored on the UTC date instead of the
event-local calendar. I fixed the test to use an unambiguous `now`, which also
made it exercise the spring-forward boundary properly (`9am NY on 03-09 →
13:00Z`). Lesson: when an AI-written test fails, check whether the *test's
premise* is wrong before "fixing" working code.
