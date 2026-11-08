"""Create the KnowledgeIngestion and outbox tables (ADR 0005).

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the tables."""
    op.execute(
        """
        CREATE TABLE knowledge_ingestion (
            ingestion_id text PRIMARY KEY,
            item_id text NOT NULL,
            version_tag text NOT NULL,
            status text NOT NULL,
            attempts integer NOT NULL,
            blocks_for_review integer,
            failure_code text,
            failure_detail text,
            request_id text,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            FOREIGN KEY (item_id, version_tag)
                REFERENCES knowledge_version (item_id, version_tag) ON DELETE CASCADE
        );
        -- Two runs of one version would overwrite each other's blocks.
        CREATE UNIQUE INDEX knowledge_ingestion_one_running_per_version
            ON knowledge_ingestion (item_id, version_tag)
            WHERE status IN ('queued', 'extracting', 'reading_pages');

        CREATE TABLE outbox_message (
            outbox_id text PRIMARY KEY,
            ingestion_id text NOT NULL
                REFERENCES knowledge_ingestion (ingestion_id) ON DELETE CASCADE,
            routing_key text NOT NULL,
            payload jsonb NOT NULL,
            created_at timestamptz NOT NULL,
            published_at timestamptz
        );
        CREATE INDEX outbox_message_unpublished
            ON outbox_message (created_at) WHERE published_at IS NULL;
        """
    )


def downgrade() -> None:
    """Drop the tables, messages first."""
    op.execute(
        """
        DROP TABLE outbox_message;
        DROP TABLE knowledge_ingestion;
        """
    )
