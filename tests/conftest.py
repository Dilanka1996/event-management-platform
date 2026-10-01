"""Shared pytest fixtures.

Tests run against the real app + DB (as configured by DATABASE_URL). The
seeded fixtures give us: user 1 = ADMIN (token tok_1), plus CONTRIBUTOR and
ATTENDEE users, events across timezones, and one event with sessions.
"""

import os

import pytest
from fastapi.testclient import TestClient

from app.main import app

ADMIN_TOKEN = os.getenv("EMP_ADMIN_TOKEN", "tok_1")


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_headers():
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
