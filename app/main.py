"""Dummy FastAPI entrypoint for the event-management-platform backend.

The Docker image runs:  uvicorn app.main:app
`make up` waits on:      GET /health
"""

import os

from fastapi import FastAPI

app = FastAPI(
    title="Event Management Platform",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness/readiness probe used by docker-compose and `make up`."""
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "event-management-platform",
        "version": app.version,
        # Sanity check that DATABASE_URL is reaching the container.
        "db_configured": str("DATABASE_URL" in os.environ).lower(),
        "docs": "/docs",
    }
