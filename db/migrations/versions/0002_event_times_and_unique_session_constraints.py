"""add event start/end times + indexes for room-conflict checks

Revision ID: 0002
Revises: 0001
Create Date: 2025-01-02

Adds the scheduling columns events were missing so that events (and their
sessions) can be reasoned about across time zones and DST boundaries. All
timestamps are stored as TIMESTAMPTZ (UTC instants); the events.timezone
column carries the IANA zone used to render wall-clock local time.

Hand-written SQL to match 0001.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Events gain a scheduling window. Nullable so pre-existing rows survive;
    # new rows created via the API always set both.
    op.execute(
        """
        ALTER TABLE events
            ADD COLUMN start_time TIMESTAMPTZ,
            ADD COLUMN end_time   TIMESTAMPTZ;
        """
    )
    op.execute(
        "ALTER TABLE events "
        "ADD CONSTRAINT events_time_order CHECK (end_time > start_time);"
    )

    # A room cannot host two sessions that overlap. This is enforced in the
    # application (so we can return a clean 409 + the conflicting session) but
    # the index keeps the free-room lookup fast at 50k scale.
    op.execute("CREATE INDEX idx_sessions_event_time ON sessions (event_id, start_time, end_time);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_sessions_event_time;")
    op.execute("ALTER TABLE events DROP CONSTRAINT IF EXISTS events_time_order;")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS end_time;")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS start_time;")
