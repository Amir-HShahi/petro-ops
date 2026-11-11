"""Add the transfer rules of each Layer (spec §10.1).

The rule columns are empty until a rule is defined, and are set or empty together.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the columns."""
    op.execute(
        """
        ALTER TABLE layer
            ADD COLUMN required_topics TEXT[],
            ADD COLUMN excluded_topics TEXT[],
            ADD COLUMN output_format TEXT,
            ADD COLUMN min_judge_score_points SMALLINT
                CHECK (min_judge_score_points BETWEEN 1 AND 20),
            ADD COLUMN max_package_length_tokens INTEGER
                CHECK (max_package_length_tokens > 0),
            ADD COLUMN source_reference_level TEXT,
            ADD CONSTRAINT layer_transfer_rule_complete CHECK (
                num_nulls(required_topics, excluded_topics, output_format,
                          min_judge_score_points, max_package_length_tokens,
                          source_reference_level) IN (0, 6)
            ),
            -- Layer 4 only provides knowledge, so it never has transfer rules.
            ADD CONSTRAINT layer_four_has_no_transfer_rule CHECK (
                layer_index <> 4 OR output_format IS NULL
            );
        """
    )


def downgrade() -> None:
    """Drop the columns."""
    op.execute(
        """
        ALTER TABLE layer
            DROP COLUMN required_topics,
            DROP COLUMN excluded_topics,
            DROP COLUMN output_format,
            DROP COLUMN min_judge_score_points,
            DROP COLUMN max_package_length_tokens,
            DROP COLUMN source_reference_level;
        """
    )
