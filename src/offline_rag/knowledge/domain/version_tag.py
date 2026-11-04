"""The immutable id of a KnowledgeVersion."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VersionTag:
    """Immutable id of a KnowledgeVersion, unique within its KnowledgeItem (spec §5.3, §7.6)."""

    value: str

    @classmethod
    def for_sequence_number(cls, sequence_number: int) -> "VersionTag":
        """Return the tag of the version with this sequence number, such as `v1`."""
        return cls(f"v{sequence_number}")

    def __str__(self) -> str:
        return self.value
