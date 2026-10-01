"""Verify seeded data by logging the row count and 10 sample rows per table.

Run with:  poetry run python -m scripts.verify_seed
"""

import sys

from sqlalchemy import text

from app.db import engine

TABLES = ["users", "events", "event_roles", "sessions", "invitations"]
SAMPLE_ROWS = 10


def verify(conn) -> None:
    for table in TABLES:
        try:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
        except Exception as err:  # noqa: BLE001
            print(f"[verify] {table}: ERROR counting rows: {err}", file=sys.stderr)
            continue

        print(f"\n[verify] {table} — {count} rows")
        rows = conn.execute(
            text(f"SELECT * FROM {table} ORDER BY id LIMIT :n"),
            {"n": SAMPLE_ROWS},
        ).mappings()

        columns = None
        printed = 0
        for row in rows:
            if columns is None:
                columns = list(row.keys())
                print("  " + " | ".join(str(c) for c in columns))
                print("  " + "-" * 40)
            print("  " + " | ".join(str(row[c]) for c in columns))
            printed += 1

        if printed == 0:
            print("  (no rows)")


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
    print(f"[verify] database not reachable: {last_err}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    wait_for_db()
    with engine.connect() as conn:
        verify(conn)
    print("\n[verify] done")


if __name__ == "__main__":
    main()
