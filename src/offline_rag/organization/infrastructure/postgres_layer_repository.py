"""Layer storage in the local Postgres database. Migration 0004 loads the five Layers."""

from typing import Any

from offline_rag.organization.application.errors import LayerNotFoundError
from offline_rag.organization.domain.layer import Layer
from offline_rag.organization.domain.transfer_detail_level import TransferDetailLevel
from offline_rag.organization.infrastructure.postgres_database import PostgresDatabase
from offline_rag.shared_kernel.layer_index import LayerIndex


class PostgresLayerRepository:
    """Reads the Layers from the `layer` table."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def get_by_index(self, layer_index: LayerIndex) -> Layer:
        """Return the Layer at this index.

        Raises:
            LayerNotFoundError: The Layer is not in the table.
            OrganizationStorageError: The database cannot be read.
        """
        with self._database.transaction("get_by_index") as connection:
            row = connection.execute(
                "SELECT * FROM layer WHERE layer_index = %s", (layer_index.value,)
            ).fetchone()
        if row is None:
            raise LayerNotFoundError(layer_index.value)
        return _layer_from_row(row)

    def find_all(self) -> list[Layer]:
        """Return every Layer, from Layer 0 down.

        Raises:
            OrganizationStorageError: The database cannot be read.
        """
        with self._database.transaction("find_all_layers") as connection:
            rows = connection.execute("SELECT * FROM layer ORDER BY layer_index").fetchall()
        return [_layer_from_row(row) for row in rows]


def _layer_from_row(row: dict[str, Any]) -> Layer:
    detail_level = row["received_detail_level"]
    return Layer(
        layer_index=LayerIndex(row["layer_index"]),
        name=row["name"],
        role=row["role"],
        received_detail_level=TransferDetailLevel(detail_level) if detail_level else None,
    )
