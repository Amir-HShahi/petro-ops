"""Inputs of the Organizational Hierarchy use cases."""

from dataclasses import dataclass

from offline_rag.shared_kernel.confidentiality_level import ConfidentialityLevel
from offline_rag.shared_kernel.layer_index import LayerIndex
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


@dataclass(frozen=True, kw_only=True)
class RegisterNode:
    """Add a Node to the hierarchy (spec §6.1).

    Attributes:
        node_id: Stable id of the new Node, such as `sp12_inspection_team`.
        name: Display name.
        layer_index: The one Layer the Node belongs to.
        parent_node_id: The registered Node it reports to; None only in Layer 0.
        activity_area: What the Node works on.
        reporting_rule: How often it reports to its parent, such as `weekly`.
        confidentiality: The visibility limit of the Node's knowledge.
        is_internal_structure_tracked: Whether the Node's children are modelled.
    """

    node_id: NodeIdentifier
    name: str
    layer_index: LayerIndex
    parent_node_id: NodeIdentifier | None
    activity_area: str
    reporting_rule: str
    confidentiality: ConfidentialityLevel
    is_internal_structure_tracked: bool
