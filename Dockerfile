# FastAPI backend image (Poetry-managed). DB runs as its own service in compose.
# The intent-classifier LLM runs IN-PROCESS via llama-cpp-python (Qwen2.5-1.5B
# GGUF), so there is no Ollama server, no port, and no sidecar service.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_VIRTUALENVS_CREATE=false \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/root/.cache/huggingface

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

# Pre-download the GGUF into the image layer so the first classification does
# not pay a ~1GB download at runtime. Override the model with LLM_MODEL.
# NOTE: compose mounts the `hf_cache` named volume at $HF_HOME. Docker seeds a
# NEW named volume from the image layer, so this cache is carried into it on
# first run; subsequent runs reuse the volume without re-downloading.
ARG LLM_MODEL=Qwen/Qwen2.5-1.5B-Instruct-GGUF
ARG LLM_MODEL_FILE=qwen2.5-1.5b-instruct-q4_k_m.gguf
RUN python -c "from llama_cpp import Llama; \
Llama.from_pretrained(repo_id='${LLM_MODEL}', filename='${LLM_MODEL_FILE}')" \
    || echo "model predownload skipped (will download on first use)"
EXPOSE 8000
# --reload streams live code changes during `make up` development.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

