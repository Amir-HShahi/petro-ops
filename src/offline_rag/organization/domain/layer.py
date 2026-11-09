"""The Layer aggregate root."""

from dataclasses import dataclass

from offline_rag.organization.domain.errors import InvalidLayerDetailLevelError
from offline_rag.organization.domain.transfer_detail_level import TransferDetailLevel
from offline_rag.shared_kernel.layer_index import LayerIndex


@dataclass(frozen=True, kw_only=True)
class Layer:
    """One level of the organizational hierarchy (spec §6.1, §6.2).

    Invariants:
    - Layer 4 only provides knowledge, so it receives no TransferPackage and has no
      detail level (registry README).
    - Every other Layer receives knowledge from the Layer below at one detail level
      (spec §6.4).

    Attributes:
        layer_index: Position in the hierarchy; 0 is the top.
        name: Short name, such as "Parent organizations".
        role: Who sits in this Layer in the case study, such as "Regional operators".
        received_detail_level: How detailed the knowledge from the Layer below must
            be; None for Layer 4.

    Raises:
        InvalidLayerDetailLevelError: The detail level breaks an invariant.
    """

    layer_index: LayerIndex
    name: str
    role: str
    received_detail_level: TransferDetailLevel | None

    def __post_init__(self) -> None:
        has_detail_level = self.received_detail_level is not None
        if has_detail_level == self.layer_index.is_knowledge_source:
            raise InvalidLayerDetailLevelError(
                layer_index=self.layer_index.value,
                detail_level=self.received_detail_level,
            )

    @property
    def receives_transfer_package(self) -> bool:
        """Whether the Layer below sends this Layer a TransferPackage."""
        return self.received_detail_level is not None
