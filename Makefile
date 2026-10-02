.PHONY: up db seed test test-llm chat model-warm down clean logs psql build-backend agent-eval openapi-snapshot

# 1. Boot DB + Backend (the LLM runs in-process in the backend), wait for
#    readiness, warm the model, then drop into the interactive chat CLI in the
#    foreground. Exit the chat to return (containers keep running; `make down`
#    stops them). Fully containerised — no host Ollama / model server needed.
up: build-backend
	docker compose up -d --build
	@echo "Waiting for PostgreSQL & FastAPI backend to be online..."
	@until curl -s http://localhost:8000/health > /dev/null; do \
		sleep 1; \
	done
	@echo "Backend is online."
	@$(MAKE) --no-print-directory model-warm
	@echo "Starting chat CLI (type 'exit' or Ctrl-D to quit)..."
	@docker compose run --rm --entrypoint "" -it backend python -m agent.chat

# 2. Run migrations and seed the DB (50 events / 5k users / 50k invitations)
#    Runs inside the backend image, so no local Python/Poetry needed.
seed: db build-backend
	docker compose run --rm --entrypoint "" backend alembic upgrade head
	docker compose run --rm --entrypoint "" backend python -m scripts.seed_data
	docker compose run --rm --entrypoint "" backend python -m scripts.verify_seed

# Build (or refresh) the backend image so local file changes are copied in.
build-backend:
	docker compose build backend > /dev/null

# 3. Execute test suite against backend API (runs seed so authz fixtures exist)
#    Deterministic: no LLM required.
test: seed
	docker compose run --rm --entrypoint "" backend pytest -v --tb=short

# 3c. LLM-backed tests: intent classification against the real in-process model.
#     `make model-warm` first so the GGUF is cached in the image/volume.
test-llm: build-backend
	docker compose run --rm --entrypoint "" backend \
		pytest -v --tb=short agent/tests/test_classifier_llm.py

# 3d. Interactive chat with the agent (in-process LLM + gated loop).
#     Warm the model first with `make model-warm`.
chat: build-backend
	docker compose run --rm --entrypoint "" -it backend python -m agent.chat

# Load the configured GGUF in-process so it's cached (image layer / hf_cache
# volume) before the first real request. No-ops if already present.
model-warm: build-backend
	@echo "Warming in-process model ($${LLM_MODEL:-Qwen/Qwen2.5-1.5B-Instruct-GGUF})..."
	@docker compose run --rm --entrypoint "" backend \
		python -c "from agent.classifier import IntentClassifier; \
IntentClassifier()._ensure_loaded(); print('model ready.')"

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

