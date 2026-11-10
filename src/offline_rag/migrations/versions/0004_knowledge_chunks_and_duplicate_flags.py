"""Add chunks, duplicate flags, the text hash and the chunking step (ADR 0009, ADR 0010).

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the tables and columns, and let a chunking run count as running."""
    op.execute(
        """
        ALTER TABLE knowledge_version ADD COLUMN normalized_text_hash text;
        CREATE INDEX knowledge_version_by_normalized_text_hash
            ON knowledge_version (normalized_text_hash);

        ALTER TABLE knowledge_ingestion ADD COLUMN chunk_count integer;

        DROP INDEX knowledge_ingestion_one_running_per_version;
        CREATE UNIQUE INDEX knowledge_ingestion_one_running_per_version
            ON knowledge_ingestion (item_id, version_tag)
            WHERE status IN ('queued', 'extracting', 'reading_pages', 'chunking');

        CREATE TABLE knowledge_chunk (
            item_id text NOT NULL,
            version_tag text NOT NULL,
            chunk_order integer NOT NULL,
            chunk_id text NOT NULL UNIQUE,
            text text NOT NULL,
            token_count integer NOT NULL,
            heading_path jsonb NOT NULL,
            page_start integer,
            page_end integer,
            first_block_order integer NOT NULL,
            last_block_order integer NOT NULL,
            metadata jsonb NOT NULL,
            PRIMARY KEY (item_id, version_tag, chunk_order),
            FOREIGN KEY (item_id, version_tag)
                REFERENCES knowledge_version (item_id, version_tag) ON DELETE CASCADE
        );

        CREATE TABLE knowledge_duplicate_flag (
            item_id text NOT NULL,
            version_tag text NOT NULL,
            existing_item_id text NOT NULL,
            existing_version_tag text NOT NULL,
            kind text NOT NULL,
            score double precision NOT NULL,
            is_ambiguous boolean NOT NULL,
            PRIMARY KEY (item_id, version_tag, existing_item_id),
            FOREIGN KEY (item_id, version_tag)
                REFERENCES knowledge_version (item_id, version_tag) ON DELETE CASCADE,
            FOREIGN KEY (existing_item_id, existing_version_tag)
                REFERENCES knowledge_version (item_id, version_tag) ON DELETE CASCADE
        );
        """
    )


def downgrade() -> None:
    """Drop what `upgrade` added.

    Runs waiting for chunking go back to QUEUED, which the older code knows; the
    reconciler then sends them through extraction again.
    """
    op.execute(
        """
        DROP TABLE knowledge_duplicate_flag;
        DROP TABLE knowledge_chunk;

        UPDATE knowledge_ingestion SET status = 'queued' WHERE status = 'chunking';
        DROP INDEX knowledge_ingestion_one_running_per_version;
        CREATE UNIQUE INDEX knowledge_ingestion_one_running_per_version
            ON knowledge_ingestion (item_id, version_tag)
            WHERE status IN ('queued', 'extracting', 'reading_pages');

        ALTER TABLE knowledge_ingestion DROP COLUMN chunk_count;

        DROP INDEX knowledge_version_by_normalized_text_hash;
        ALTER TABLE knowledge_version DROP COLUMN normalized_text_hash;
        """
    )
