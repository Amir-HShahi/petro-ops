"""The Node id that Organizational Hierarchy publishes to every other context."""

from dataclasses import dataclass

from offline_rag.shared_kernel.errors import InvalidNodeIdentifierError


@dataclass(frozen=True, slots=True)
class NodeIdentifier:
    """Stable id of a Node (spec §5.3), such as `sp12_inspection_team`.

    Raises:
        InvalidNodeIdentifierError: The value is empty or has spaces around it.
    """

    value: str

    def __post_init__(self) -> None:
        if not self.value or self.value != self.value.strip():
            raise InvalidNodeIdentifierError(self.value)

    def __str__(self) -> str:
        return self.value
