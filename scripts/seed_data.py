"""Seed the database with bulk fixtures.

Run with:  poetry run python -m scripts.seed_data

Seeds 50 events / 5k users / 50k invitations for pagination and scale testing.
"""

import sys

from sqlalchemy import text

from app.db import engine

EVENTS = 50
USERS = 5000
INVITATIONS = 50000


def seed(conn) -> None:
    print(f"[seed] {EVENTS} events / {USERS} users / {INVITATIONS} invitations")

    conn.execute(
        text(
            """
            INSERT INTO users (email, name, api_token)
            SELECT 'user_' || g || '@example.com',
                   'User ' || g,
                   'tok_' || g
            FROM generate_series(1, :n) AS g
            ON CONFLICT (email) DO NOTHING
            """
        ),
        {"n": USERS},
    )

    conn.execute(
        text(
            """
            INSERT INTO events (title, description, timezone)
            SELECT 'Event ' || g,
                   'Auto-generated event ' || g,
                   'UTC'
            FROM generate_series(1, :n) AS g
            """
        ),
        {"n": EVENTS},
    )

    # Spread invitations evenly across events (exactly INVITATIONS rows total).
    conn.execute(
        text(
            """
            INSERT INTO invitations (event_id, email, status)
            SELECT e.id,
                   'invitee_' || g || '@example.com',
                   'PENDING'
            FROM generate_series(1, :n) AS g
            JOIN LATERAL (
                SELECT id FROM events ORDER BY id LIMIT 1 OFFSET (g % :ne)
            ) AS e ON true
            ON CONFLICT (event_id, email) DO NOTHING
            """
        ),
        {"n": INVITATIONS, "ne": EVENTS},
    )

    print("[seed] done")


def wait_for_db(retries: int = 30, delay: float = 1.0) -> None:
    import time

    last_err = None
    for _ in range(retries):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as err:  # noqa: BLE001
            last_err = err
            time.sleep(delay)
    print(f"[seed] database not reachable: {last_err}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    wait_for_db()
    with engine.begin() as conn:
        seed(conn)


if __name__ == "__main__":
    main()
