"""Random ids for new aggregates."""

import uuid


class UuidIdGenerator:
    """Creates random UUID4 ids, so ids never depend on order or on another store."""

    def new_id(self) -> str:
        """Return a new UUID4 as text."""
        return str(uuid.uuid4())
