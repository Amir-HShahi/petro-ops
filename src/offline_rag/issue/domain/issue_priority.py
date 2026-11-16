"""How urgent an Issue is (spec §12.3, §14.2)."""

from enum import StrEnum


class IssuePriority(StrEnum):
    """The priority a person gives an Issue.

    The spec names a priority but gives no scale (docs/application-services.md,
    AOQ 5), so it is four levels set by hand. The factors of spec §14.2 may later
    suggest a level.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
