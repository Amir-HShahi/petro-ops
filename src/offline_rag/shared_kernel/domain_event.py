"""Base type for domain events in every context."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Something important that happened in the domain (spec §5). An event never changes.

    Attributes:
        occurred_at: When it happened, as a timezone-aware time.
    """

    occurred_at: datetime
