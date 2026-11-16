"""Create the table of similar-Issue flags (ADR 0012).

A flag belongs to the new Issue that was found to look like an older Issue of the
same Node. The older Issue is not a foreign key: a flag records what was found when
the new Issue was raised.

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the table."""
    op.execute(
        """
        CREATE TABLE similar_issue_flag (
            issue_id TEXT NOT NULL REFERENCES issue (issue_id) ON DELETE CASCADE,
            similar_issue_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('duplicate', 'overlap')),
            score DOUBLE PRECISION NOT NULL CHECK (score >= 0 AND score <= 1),
            PRIMARY KEY (issue_id, similar_issue_id),
            CHECK (similar_issue_id <> issue_id)
        );
        """
    )


def downgrade() -> None:
    """Drop the table."""
    op.execute("DROP TABLE similar_issue_flag;")
