"""Create the table of SubIssue candidates the LLM suggests (spec §12.2).

An accepted candidate names the SubIssue it became, which must exist in the same
Issue. Citations are kept as JSON, since they are only read with their candidate.

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the table."""
    op.execute(
        """
        CREATE TABLE sub_issue_candidate (
            issue_id TEXT NOT NULL REFERENCES issue (issue_id) ON DELETE CASCADE,
            number INTEGER NOT NULL CHECK (number >= 1),
            title TEXT NOT NULL CHECK (btrim(title) <> ''),
            description TEXT NOT NULL CHECK (btrim(description) <> ''),
            citations JSONB NOT NULL,
            accepted_sub_issue_id TEXT,
            PRIMARY KEY (issue_id, number),
            FOREIGN KEY (issue_id, accepted_sub_issue_id)
                REFERENCES sub_issue (issue_id, sub_issue_id)
        );
        """
    )


def downgrade() -> None:
    """Drop the table."""
    op.execute("DROP TABLE sub_issue_candidate;")
