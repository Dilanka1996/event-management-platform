# AI Workflow

How I used AI on this assignment: what I drove, what I delegated, how I planned,
and — most importantly — a specific case where the AI produced wrong code, how
I caught it, and what we changed.

## Tools used

- **VS Code + [Continue](https://continue.dev) with a DeepSeek model** as the
  primary coding assistant. This was the agent-mode setup I actually worked in:
  Continue patched files in-editor, ran the terminal, and I reviewed every diff
  before accepting it. The DeepSeek model did the heavy lifting on code
  generation (the classifier/slot/planner/chat modules, refactors, Docker/Makefile
  wiring, test scaffolding), and I drove the architecture and accepted/rejected
  each change.

## What I drove vs. delegated

| my decisions | assistant executed |
|---|---|
| The architecture: *gate outside the model; the LLM only understands* | Writing the classifier/slot/planner/chat modules |
| Rejecting LangChain as the agent (after auditing the 9 requirements against it) | Producing the requirement-by-requirement audit that informed that call |
| Choosing L1 (LLM understanding) **with deterministic resolution** of the dangerous slots | The `parse_when` date grammar, email/role validators |
| Accepting/rejecting each Docker, lockfile, and dependency change | Compose/Makefile edits, test scaffolding |


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
- Dropped the co-located `ollama serve` idea entirely: no port, no server, no
  entrypoint supervisor. (The model first moved in-process via `llama-cpp-python`
  + a Qwen GGUF — ADR 0004 — and was later replaced by the hosted OpenAI API —
  ADR 0005 — which also removed the baked weights. The lesson below is about the
  *edge*, not the transport.)
- `make test` never touches the model at all; `make test-llm` / `make chat` are
  the only paths that call it.
