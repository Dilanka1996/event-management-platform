.PHONY: up db seed test test-llm chat ollama-pull down clean logs psql build-backend agent-eval openapi-snapshot

# 1. Boot both DB and Backend (detached), wait for readiness, then stream
#    the FastAPI server's live logs in the foreground. Ctrl-C detaches the
#    log stream; the containers keep running (use `make down` to stop them).
up:
	docker compose up -d --build
	@echo "Waiting for FastAPI backend to be online..."
	@until curl -s http://localhost:8000/health > /dev/null; do \
		sleep 1; \
	done
	@echo "PostgreSQL & FastAPI backend are online. Streaming backend logs (Ctrl-C to detach)..."
	@docker compose logs -f backend

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

# 3c. LLM-backed tests: intent classification against the real local Ollama model.
#     Requires a natively-running Ollama with the model pulled (`make ollama-pull`).
test-llm: build-backend
	docker compose run --rm --entrypoint "" backend \
		pytest -v --tb=short agent/tests/test_classifier_llm.py

# 3d. Interactive chat with the agent (local Ollama understanding + gated loop).
#     Ollama runs on the HOST; the backend container reaches it via
#     host.docker.internal (see docker-compose.yaml).
chat: build-backend
	docker compose run --rm --entrypoint "" -it backend python -m agent.chat

# Pull the configured Ollama model on the HOST (no ollama container).
# Requires Ollama installed and listening on localhost:11434.
ollama-pull:
	@echo "Pulling Ollama model $${OLLAMA_MODEL:-llama3.2:3b} on the host..."
	@ollama pull $${OLLAMA_MODEL:-llama3.2:3b}

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



