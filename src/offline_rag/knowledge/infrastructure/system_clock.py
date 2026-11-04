"""The real clock."""

from datetime import UTC, datetime


class SystemClock:
    """Tells the current time in UTC."""

    def now(self) -> datetime:
        """Return the current time, timezone-aware in UTC."""
        return datetime.now(UTC)
