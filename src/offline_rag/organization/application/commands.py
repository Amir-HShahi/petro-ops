"""Inputs of the Organizational Hierarchy use cases."""

from dataclasses import dataclass

from offline_rag.organization.domain.transfer_detail_level import TransferDetailLevel
from offline_rag.shared_kernel.confidentiality_level import ConfidentialityLevel
from offline_rag.shared_kernel.judge_threshold import JudgeThreshold
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


@dataclass(frozen=True, kw_only=True)
class DefineTransferRule:
    """Set what a Layer requires of the TransferPackages it receives (spec §10.1).

    Attributes:
        layer_index: The Layer that receives the packages; 0 to 3.
        received_detail_level: How detailed the packages must be (spec §6.4).
        required_topics: Topics every package must cover.
        excluded_topics: Topics no package may include.
        output_format: The preferred format of a package.
        min_judge_score: The lowest judge score a package needs to be accepted.
        max_package_length_tokens: The longest a package may be, in tokens.
        source_reference_level: How precisely a package cites its sources.
    """

    layer_index: LayerIndex
    received_detail_level: TransferDetailLevel
    required_topics: tuple[str, ...]
    excluded_topics: tuple[str, ...]
    output_format: str
    min_judge_score: JudgeThreshold
    max_package_length_tokens: int
    source_reference_level: str
