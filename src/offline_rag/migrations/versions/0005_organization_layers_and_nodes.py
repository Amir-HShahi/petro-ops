"""Create the Layer and Node tables of Organizational Hierarchy, and load the five Layers.

The Layers exist from the start (docs/domain-model.md, section 11), so they are
loaded here, with the values of `fixtures/registry/layers.csv` (spec §6.2, §6.4).

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the tables and load the Layers."""
    op.execute(
        """
        CREATE TABLE layer (
            layer_index SMALLINT PRIMARY KEY CHECK (layer_index BETWEEN 0 AND 4),
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            received_detail_level TEXT
                CHECK (received_detail_level IN
                    ('top_executive', 'managerial', 'technical_summary', 'detailed_technical')),
            -- Layer 4 only provides knowledge; every other Layer receives one detail level.
            CHECK ((layer_index = 4) = (received_detail_level IS NULL))
        );

        INSERT INTO layer (layer_index, name, role, received_detail_level) VALUES
            (0, 'Strategic', 'National Oil Company', 'top_executive'),
            (1, 'Parent organizations', 'Regional operators', 'managerial'),
            (2, 'Subsidiaries and units', 'Offshore fields and platforms', 'technical_summary'),
            (3, 'Executive nodes', 'Inspection, maintenance, drilling and HSE teams',
                'detailed_technical'),
            (4, 'Knowledge sources',
                'Archive of standards, past incidents and personnel records', NULL);

        CREATE TABLE node (
            node_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            layer_index SMALLINT NOT NULL REFERENCES layer (layer_index),
            parent_node_id TEXT REFERENCES node (node_id),
            activity_area TEXT NOT NULL,
            reporting_rule TEXT NOT NULL,
            confidentiality TEXT NOT NULL
                CHECK (confidentiality IN ('public', 'internal', 'confidential')),
            is_internal_structure_tracked BOOLEAN NOT NULL,
            CHECK ((layer_index = 0) = (parent_node_id IS NULL))
        );

        -- Layer 0 holds the one Node at the top; this also stops two racing registrations.
        CREATE UNIQUE INDEX node_one_in_top_layer ON node (layer_index) WHERE layer_index = 0;
        CREATE INDEX node_by_parent ON node (parent_node_id);
        """
    )


def downgrade() -> None:
    """Drop the tables."""
    op.execute("DROP TABLE node; DROP TABLE layer;")
