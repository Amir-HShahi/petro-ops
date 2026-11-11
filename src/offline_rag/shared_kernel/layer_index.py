"""The Layer index that Organizational Hierarchy publishes to every other context."""

from dataclasses import dataclass

from offline_rag.shared_kernel.errors import InvalidLayerIndexError

TOP_LAYER = 0
KNOWLEDGE_SOURCE_LAYER = 4


@dataclass(frozen=True, slots=True)
class LayerIndex:
    """Position of a Layer, from 0 (strategic) to 4 (knowledge sources) (spec §6.2).

    A lower index is higher in the hierarchy.

    Raises:
        InvalidLayerIndexError: The value is not a whole number from 0 to 4.
    """

    value: int

    def __post_init__(self) -> None:
        # bool is an int in Python, so `True` would otherwise pass as Layer 1.
        if (
            isinstance(self.value, bool)
            or not isinstance(self.value, int)
            or not TOP_LAYER <= self.value <= KNOWLEDGE_SOURCE_LAYER
        ):
            raise InvalidLayerIndexError(self.value)

    @property
    def is_top(self) -> bool:
        """Whether this is Layer 0, the only Layer whose Node has no parent."""
        return self.value == TOP_LAYER

    @property
    def is_knowledge_source(self) -> bool:
        """Whether this is Layer 4, which only provides knowledge (registry README)."""
        return self.value == KNOWLEDGE_SOURCE_LAYER

    def is_above(self, other: "LayerIndex") -> bool:
        """Whether this Layer is higher in the hierarchy than `other`."""
        return self.value < other.value

    def __str__(self) -> str:
        return str(self.value)
