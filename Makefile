# Cross-platform recipe shell.
# - On Unix/macOS, make already defaults to /bin/sh; we force bash so
#   Bourne-specific syntax works consistently.
# - On Windows, make defaults to cmd.exe, which cannot parse bash syntax
#   (until/do/done, /dev/null). GNU Make sets OS=Windows_NT on Windows, so we
#   point SHELL at Git Bash there. Override with: make SHELL=/path/to/bash
ifeq ($(OS),Windows_NT)
SHELL := C:/Program Files/Git/bin/bash.exe
else
SHELL := /bin/bash
endif
.SHELLFLAGS := -eu -o pipefail -c

.PHONY: up db seed test test-llm chat down clean logs psql build-backend agent-eval openapi-snapshot

# 1. Boot DB + Backend, ensure the DB is migrated + seeded, then drop into the
#    interactive chat CLI in the foreground. Exit the chat to return (containers
#    keep running; `make down` stops them). Fully containerised.
#    The intent classifier calls the hosted OpenAI API, so set OPENAI_API_KEY in
#    your environment first (e.g. `$env:OPENAI_API_KEY="sk-..."` on Windows).
#    `seed` runs BEFORE chat so the agent never talks to an empty DB (which
#    returns HTTP 500 / "relation does not exist").
up: seed
	docker compose up -d --build
	@echo "Waiting for PostgreSQL & FastAPI backend to be online..."
	@until curl -s http://localhost:8000/health > /dev/null; do \
		sleep 1; \
	done
	@echo "Backend is online."
	@echo "Starting chat CLI (type 'exit' or Ctrl-D to quit)..."
	@docker compose run --rm --entrypoint "" -it backend python -m agent.chat

# 2. Run migrations and seed the DB (50 events / 5k users / 50k invitations)
#    Runs inside the backend image, so no local Python/Poetry needed.
seed: db build-backend
	docker compose run --rm --entrypoint "" backend alembic upgrade head
	docker compose run --rm --entrypoint "" backend python -m scripts.seed_data
	docker compose run --rm --entrypoint "" backend python -m scripts.verify_seed

# Build (or refresh) the backend image so local file changes are copied in.
# Progress is NOT hidden: the first build (or any dependency change) spends
# minutes resolving Poetry deps, and a silent build looks like a hang.
build-backend:
	@echo "Building backend image (first build resolves Poetry deps; be patient)..."
	docker compose build backend

# 3. Execute test suite against backend API (runs seed so authz fixtures exist)
#    Deterministic: no LLM required, no API key needed.
test: seed
	docker compose run --rm --entrypoint "" backend pytest -v --tb=short

# 3c. LLM-backed tests: intent classification against the real OpenAI model.
#     Requires OPENAI_API_KEY; the module skips cleanly if it is unset.
test-llm: build-backend
	docker compose run --rm --entrypoint "" backend \
		pytest -v --tb=short agent/tests/test_classifier_llm.py

# 3d. Interactive chat with the agent (OpenAI classifier + gated loop).
#     Requires OPENAI_API_KEY.
chat: build-backend
	docker compose run --rm --entrypoint "" -it backend python -m agent.chat

# 3b. Regenerate the committed OpenAPI contract snapshot (only when intended).
openapi-snapshot: build-backend
	docker compose run --rm --entrypoint "" backend \
		python -m scripts.snapshot_openapi

# 4. Run the agent eval suite (~15 scripted scenarios) and report pass rate.
agent-eval: build-backend
	docker compose run --rm --entrypoint "" backend \
		python -m agent.scenarios

# Ensure the database service is running (used as a prerequisite)
db:
	@docker compose up -d db
	@echo "Waiting for PostgreSQL to be ready..."
	@until docker compose exec -T db pg_isready -U $${POSTGRES_USER:-emp} > /dev/null 2>&1; do \
		sleep 1; \
	done
	@echo "PostgreSQL is ready."

# Clean up containers and volumes for fresh test runs
down clean:
	docker compose down -v

# Tail logs (e.g. make logs s=backend)
logs:
	docker compose logs -f $(s)

# Open a psql shell into the database
psql:
	docker compose exec db psql -U $${POSTGRES_USER:-emp} -d $${POSTGRES_DB:-emp}
