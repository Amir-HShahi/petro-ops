"""Create the Issue and SubIssue tables of Issue Management.

The owner Node is not a foreign key to `node`: each bounded context keeps its own
tables, and the owner is checked through Organizational Hierarchy when an Issue is
raised.

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_STATUSES = (
    "'new', 'analyzing', 'knowledge_identified', 'executor_identified', 'solution_proposed', "
    "'in_execution', 'awaiting_decision', 'resolved', 'unresolved', 'archived'"
)


def upgrade() -> None:
    """Create the tables."""
    op.execute(
        f"""
        CREATE TABLE issue (
            issue_id TEXT PRIMARY KEY CHECK (btrim(issue_id) <> ''),
            owner_node_id TEXT NOT NULL,
            title TEXT NOT NULL CHECK (btrim(title) <> ''),
            description TEXT NOT NULL CHECK (btrim(description) <> ''),
            metadata JSONB NOT NULL,
            status TEXT NOT NULL CHECK (status IN ({_STATUSES})),
            raised_at TIMESTAMPTZ NOT NULL
        );

        CREATE INDEX issue_by_owner ON issue (owner_node_id, raised_at);

        CREATE TABLE sub_issue (
            issue_id TEXT NOT NULL REFERENCES issue (issue_id) ON DELETE CASCADE,
            sub_issue_id TEXT NOT NULL CHECK (btrim(sub_issue_id) <> ''),
            -- The Issue id itself, or another SubIssue of the same Issue.
            parent_id TEXT NOT NULL,
            position INTEGER NOT NULL CHECK (position >= 1),
            title TEXT NOT NULL CHECK (btrim(title) <> ''),
            description TEXT NOT NULL CHECK (btrim(description) <> ''),
            metadata JSONB NOT NULL,
            status TEXT NOT NULL CHECK (status IN ({_STATUSES})),
            PRIMARY KEY (issue_id, sub_issue_id),
            UNIQUE (issue_id, parent_id, position)
        );
        """
    )


def downgrade() -> None:
    """Drop the tables."""
    op.execute("DROP TABLE sub_issue; DROP TABLE issue;")
