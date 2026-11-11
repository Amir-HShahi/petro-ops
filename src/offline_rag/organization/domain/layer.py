"""The Layer aggregate root."""

from datetime import datetime

from offline_rag.organization.domain.errors import (
    InvalidLayerDetailLevelError,
    LayerReceivesNoTransferPackageError,
)
from offline_rag.organization.domain.events import LayerTransferRuleDefined
from offline_rag.organization.domain.transfer_detail_level import TransferDetailLevel
from offline_rag.organization.domain.transfer_rule import TransferRule
from offline_rag.shared_kernel.domain_event import DomainEvent
from offline_rag.shared_kernel.layer_index import LayerIndex


class Layer:
    """One level of the organizational hierarchy (spec §6.1, §6.2).

    Invariants:
    - Layer 4 only provides knowledge, so it receives no TransferPackage, has no
      detail level and no transfer rules (registry README).
    - Every other Layer receives knowledge from the Layer below at one detail level
      (spec §6.4), and may have transfer rules (spec §10.1).
    """

    def __init__(
        self,
        *,
        layer_index: LayerIndex,
        name: str,
        role: str,
        received_detail_level: TransferDetailLevel | None,
        transfer_rule: TransferRule | None = None,
    ) -> None:
        """Rebuild a Layer, for example from storage.

        Args:
            layer_index: Position in the hierarchy; 0 is the top.
            name: Short name, such as "Parent organizations".
            role: Who sits in this Layer in the case study, such as "Regional operators".
            received_detail_level: How detailed the knowledge from the Layer below must
                be; None for Layer 4.
            transfer_rule: What the packages this Layer receives must meet; None until
                defined, and always None for Layer 4.

        Raises:
            InvalidLayerDetailLevelError: The detail level breaks an invariant.
            LayerReceivesNoTransferPackageError: Layer 4 was given transfer rules.
        """
        _check_detail_level(layer_index, received_detail_level)
        if transfer_rule is not None and layer_index.is_knowledge_source:
            raise LayerReceivesNoTransferPackageError(layer_index.value)
        self._layer_index = layer_index
        self._name = name
        self._role = role
        self._received_detail_level = received_detail_level
        self._transfer_rule = transfer_rule
        self._pending_events: list[DomainEvent] = []

    @property
    def layer_index(self) -> LayerIndex:
        """Position in the hierarchy; 0 is the top."""
        return self._layer_index

    @property
    def name(self) -> str:
        """Short name of the Layer."""
        return self._name

    @property
    def role(self) -> str:
        """Who sits in this Layer in the case study."""
        return self._role

    @property
    def received_detail_level(self) -> TransferDetailLevel | None:
        """How detailed the knowledge from the Layer below must be; None for Layer 4."""
        return self._received_detail_level

    @property
    def transfer_rule(self) -> TransferRule | None:
        """What the packages this Layer receives must meet; None until defined."""
        return self._transfer_rule

    @property
    def receives_transfer_package(self) -> bool:
        """Whether the Layer below sends this Layer a TransferPackage."""
        return self._received_detail_level is not None

    def define_transfer_rule(
        self,
        *,
        received_detail_level: TransferDetailLevel,
        transfer_rule: TransferRule,
        defined_at: datetime,
    ) -> None:
        """Set the detail level and transfer rules of this Layer, replacing earlier ones.

        The Layer records `LayerTransferRuleDefined`; take it with `pull_events`.

        Raises:
            LayerReceivesNoTransferPackageError: This is Layer 4.
        """
        if self._layer_index.is_knowledge_source:
            raise LayerReceivesNoTransferPackageError(self._layer_index.value)
        self._received_detail_level = received_detail_level
        self._transfer_rule = transfer_rule
        self._pending_events.append(
            LayerTransferRuleDefined(
                occurred_at=defined_at,
                layer_index=self._layer_index,
                received_detail_level=received_detail_level,
                transfer_rule=transfer_rule,
            )
        )

    def pull_events(self) -> tuple[DomainEvent, ...]:
        """Return the events recorded since the last call, and forget them."""
        events = tuple(self._pending_events)
        self._pending_events.clear()
        return events

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Layer) and other.layer_index == self._layer_index

    def __hash__(self) -> int:
        return hash(self._layer_index)


def _check_detail_level(
    layer_index: LayerIndex, received_detail_level: TransferDetailLevel | None
) -> None:
    if (received_detail_level is not None) == layer_index.is_knowledge_source:
        raise InvalidLayerDetailLevelError(
            layer_index=layer_index.value, detail_level=received_detail_level
        )
