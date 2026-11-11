"""Domain events of Organizational Hierarchy (docs/domain-model.md, section 1)."""

from dataclasses import dataclass

from offline_rag.organization.domain.transfer_detail_level import TransferDetailLevel
from offline_rag.organization.domain.transfer_rule import TransferRule
from offline_rag.shared_kernel.domain_event import DomainEvent
from offline_rag.shared_kernel.layer_index import LayerIndex
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


@dataclass(frozen=True, kw_only=True)
class NodeRegistered(DomainEvent):
    """A Node joined the hierarchy in its Layer (spec §6.1).

    Attributes:
        parent_node_id: None only for the Layer 0 Node.
    """

    node_id: NodeIdentifier
    layer_index: LayerIndex
    parent_node_id: NodeIdentifier | None


@dataclass(frozen=True, kw_only=True)
class LayerTransferRuleDefined(DomainEvent):
    """A Layer got new transfer rules for the packages it receives (spec §10.1)."""

    layer_index: LayerIndex
    received_detail_level: TransferDetailLevel
    transfer_rule: TransferRule
