"""Add the priority and resolution of an Issue, and dependencies between SubIssues.

Moving a SubIssue renumbers its siblings in one save, so for a moment two of them
hold the same place. The place of a SubIssue among its siblings is therefore checked
at commit instead of at each row.

Revision ID: 0010
Revises: 0009
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the columns, the dependency table and the deferred place check."""
    op.execute(
        """
        ALTER TABLE issue
            ADD COLUMN priority TEXT CHECK (priority IN ('low', 'medium', 'high', 'critical')),
            ADD COLUMN resolution_summary TEXT,
            -- A resolved Issue says how it was solved; any other keeps no summary.
            ADD CONSTRAINT issue_resolution_only_when_resolved
                CHECK ((status = 'resolved') = (resolution_summary IS NOT NULL));

        ALTER TABLE sub_issue
            DROP CONSTRAINT sub_issue_issue_id_parent_id_position_key,
            ADD CONSTRAINT sub_issue_one_per_place UNIQUE (issue_id, parent_id, position)
                DEFERRABLE INITIALLY DEFERRED;

        CREATE TABLE sub_issue_dependency (
            issue_id TEXT NOT NULL,
            sub_issue_id TEXT NOT NULL,
            depends_on_sub_issue_id TEXT NOT NULL,
            PRIMARY KEY (issue_id, sub_issue_id, depends_on_sub_issue_id),
            FOREIGN KEY (issue_id, sub_issue_id)
                REFERENCES sub_issue (issue_id, sub_issue_id) ON DELETE CASCADE,
            FOREIGN KEY (issue_id, depends_on_sub_issue_id)
                REFERENCES sub_issue (issue_id, sub_issue_id) ON DELETE CASCADE,
            CHECK (sub_issue_id <> depends_on_sub_issue_id)
        );
        """
    )


def downgrade() -> None:
    """Drop the dependency table and the new columns, and check places at each row again."""
    op.execute(
        """
        DROP TABLE sub_issue_dependency;

        ALTER TABLE sub_issue
            DROP CONSTRAINT sub_issue_one_per_place,
            ADD CONSTRAINT sub_issue_issue_id_parent_id_position_key
                UNIQUE (issue_id, parent_id, position);

        ALTER TABLE issue
            DROP CONSTRAINT issue_resolution_only_when_resolved,
            DROP COLUMN resolution_summary,
            DROP COLUMN priority;
        """
    )
