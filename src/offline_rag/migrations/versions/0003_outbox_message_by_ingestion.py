"""Index outbox messages by ingestion, for the reconciler (ADR 0005).

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the index."""
    op.execute("CREATE INDEX outbox_message_by_ingestion ON outbox_message (ingestion_id)")


def downgrade() -> None:
    """Drop the index."""
    op.execute("DROP INDEX outbox_message_by_ingestion")
