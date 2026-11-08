"""Create the KnowledgeItem, version and extracted content tables.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the tables that ADR 0003 kept in SQLite."""
    op.execute(
        """
        CREATE TABLE knowledge_item (
            item_id text PRIMARY KEY,
            owner_node_id text NOT NULL,
            confidentiality text NOT NULL,
            usage_scope text,
            active_version_tag text NOT NULL
        );
        CREATE INDEX knowledge_item_by_owner ON knowledge_item (owner_node_id);

        CREATE TABLE knowledge_version (
            item_id text NOT NULL REFERENCES knowledge_item (item_id) ON DELETE CASCADE,
            version_tag text NOT NULL,
            sequence_number integer NOT NULL,
            source_file_name text NOT NULL,
            source_file_reference text NOT NULL,
            document_format text NOT NULL,
            content_hash text NOT NULL,
            metadata jsonb NOT NULL,
            created_at timestamptz NOT NULL,
            change_reason text,
            previous_version_tag text,
            diff_summary text,
            PRIMARY KEY (item_id, version_tag),
            UNIQUE (item_id, sequence_number)
        );
        CREATE INDEX knowledge_version_by_content_hash ON knowledge_version (content_hash);

        CREATE TABLE extracted_content (
            item_id text NOT NULL,
            version_tag text NOT NULL,
            document_format text NOT NULL,
            page_count integer,
            PRIMARY KEY (item_id, version_tag)
        );

        CREATE TABLE extracted_content_block (
            item_id text NOT NULL,
            version_tag text NOT NULL,
            block_order integer NOT NULL,
            kind text NOT NULL,
            text text NOT NULL,
            page_number integer,
            heading_path jsonb NOT NULL,
            table_rows jsonb NOT NULL,
            source text NOT NULL,
            needs_human_review boolean NOT NULL DEFAULT false,
            review_reason text,
            PRIMARY KEY (item_id, version_tag, block_order),
            FOREIGN KEY (item_id, version_tag)
                REFERENCES extracted_content (item_id, version_tag) ON DELETE CASCADE
        );
        """
    )


def downgrade() -> None:
    """Drop the tables, blocks first."""
    op.execute(
        """
        DROP TABLE extracted_content_block;
        DROP TABLE extracted_content;
        DROP TABLE knowledge_version;
        DROP TABLE knowledge_item;
        """
    )
