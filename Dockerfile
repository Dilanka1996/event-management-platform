# FastAPI backend image (Poetry-managed). DB runs as its own service in compose.
# The intent-classifier LLM is the hosted OpenAI API, so the image stays small:
# no model weights, no llama.cpp, no GPU/runtime deps are baked in.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_VIRTUALENVS_CREATE=false \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# libpq is required by psycopg to reach Postgres; curl for healthchecks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install "poetry==$POETRY_VERSION"

# Install deps first (better layer caching).
COPY pyproject.toml poetry.lock* ./
RUN poetry install --no-root --no-interaction --no-ansi
COPY . .

EXPOSE 8000
# --reload streams live code changes during `make up` development.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
