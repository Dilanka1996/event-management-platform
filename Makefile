.PHONY: up db seed test down clean logs psql build-backend agent-eval openapi-snapshot

# 1. Boot both DB and Backend, then wait for FastAPI readiness
up:
	docker compose up -d --build
	@echo "Waiting for FastAPI backend to be online..."
	@until curl -s http://localhost:8000/health > /dev/null; do \
		sleep 1; \
	done
	@echo "PostgreSQL & FastAPI backend are online and running!"

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
test: seed
	docker compose run --rm --entrypoint "" backend pytest -v --tb=short

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
