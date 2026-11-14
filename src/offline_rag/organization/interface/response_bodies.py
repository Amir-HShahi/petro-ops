"""The JSON bodies the CLI prints and the API returns, so the two stay the same."""

from typing import Any

from offline_rag.organization.domain.layer import Layer
from offline_rag.organization.domain.node import Node


def node_body(node: Node) -> dict[str, Any]:
    """Return the JSON body that describes a Node."""
    return {
        "node_id": node.node_id.value,
        "name": node.name,
        "layer_index": node.layer_index.value,
        "parent_node_id": node.parent_node_id.value if node.parent_node_id else None,
        "activity_area": node.activity_area,
        "reporting_rule": node.reporting_rule,
        "confidentiality": node.confidentiality.value,
        "is_internal_structure_tracked": node.is_internal_structure_tracked,
    }


def layer_body(layer: Layer) -> dict[str, Any]:
    """Return the JSON body that describes a Layer and its transfer rules."""
    rule = layer.transfer_rule
    detail_level = layer.received_detail_level
    return {
        "layer_index": layer.layer_index.value,
        "name": layer.name,
        "role": layer.role,
        "received_detail_level": detail_level.value if detail_level else None,
        "transfer_rule": None
        if rule is None
        else {
            "required_topics": list(rule.required_topics),
            "excluded_topics": list(rule.excluded_topics),
            "output_format": rule.output_format,
            "min_judge_score": rule.min_judge_score.points,
            "max_package_length_tokens": rule.max_package_length_tokens,
            "source_reference_level": rule.source_reference_level,
        },
    }
