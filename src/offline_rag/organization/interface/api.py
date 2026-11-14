"""Organizational Hierarchy routes for the pipeline page.

The routes call the same handlers and queries as the CLI and return the same bodies.
Errors are raised as project errors; the app that mounts the router turns them into
Problem Details (ADR 0011).
"""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from offline_rag.organization.application.commands import DefineTransferRule, RegisterNode
from offline_rag.organization.application.define_transfer_rule import DefineTransferRuleHandler
from offline_rag.organization.application.hierarchy_queries import HierarchyQueries
from offline_rag.organization.application.register_node import RegisterNodeHandler
from offline_rag.organization.domain.transfer_detail_level import TransferDetailLevel
from offline_rag.organization.interface.response_bodies import layer_body, node_body
from offline_rag.shared_kernel.confidentiality_level import ConfidentialityLevel
from offline_rag.shared_kernel.judge_threshold import (
    DEFAULT_JUDGE_THRESHOLD_POINTS,
    JudgeThreshold,
)
from offline_rag.shared_kernel.layer_index import LayerIndex
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

CREATED = 201


class RegisterNodeRequest(BaseModel):
    """The body of `POST /organization/nodes`."""

    node_id: str
    name: str
    layer_index: int
    parent_node_id: str | None = None
    activity_area: str
    reporting_rule: str
    confidentiality: ConfidentialityLevel = ConfidentialityLevel.INTERNAL
    is_internal_structure_tracked: bool = False


class DefineTransferRuleRequest(BaseModel):
    """The body of `PUT /organization/layers/{layer_index}/transfer-rule`."""

    received_detail_level: TransferDetailLevel
    required_topics: list[str] = Field(default_factory=list)
    excluded_topics: list[str] = Field(default_factory=list)
    output_format: str
    min_judge_score: int = DEFAULT_JUDGE_THRESHOLD_POINTS
    max_package_length_tokens: int
    source_reference_level: str


def create_organization_router(
    *,
    register_node_handler: RegisterNodeHandler,
    define_transfer_rule_handler: DefineTransferRuleHandler,
    queries: HierarchyQueries,
) -> APIRouter:
    """Return the routes over the Organizational Hierarchy use cases and queries.

    Args:
        register_node_handler: Adds a Node under a parent.
        define_transfer_rule_handler: Sets the transfer rules of a Layer.
        queries: Reads the Layers and the Nodes.
    """
    router = APIRouter(prefix="/organization", tags=["organization"])

    @router.get("/layers")
    def layers() -> dict[str, Any]:
        """Return the Layer registry with the detail level and transfer rules of each Layer."""
        return {"layers": [layer_body(layer) for layer in queries.list_layers()]}

    @router.get("/nodes")
    def nodes() -> dict[str, Any]:
        """Return every Node with its Layer, parent and system boundary."""
        return {"nodes": [node_body(node) for node in queries.list_nodes()]}

    @router.post("/nodes", status_code=CREATED)
    def register_node(request: RegisterNodeRequest) -> dict[str, Any]:
        """Register a Node in its Layer under a parent that may take it."""
        node = register_node_handler.register(
            RegisterNode(
                node_id=NodeIdentifier(request.node_id),
                name=request.name,
                layer_index=LayerIndex(request.layer_index),
                parent_node_id=(
                    NodeIdentifier(request.parent_node_id) if request.parent_node_id else None
                ),
                activity_area=request.activity_area,
                reporting_rule=request.reporting_rule,
                confidentiality=request.confidentiality,
                is_internal_structure_tracked=request.is_internal_structure_tracked,
            )
        )
        return node_body(node)

    @router.put("/layers/{layer_index}/transfer-rule")
    def define_transfer_rule(
        layer_index: int, request: DefineTransferRuleRequest
    ) -> dict[str, Any]:
        """Set the detail level and transfer rules of a Layer that receives packages."""
        layer = define_transfer_rule_handler.define(
            DefineTransferRule(
                layer_index=LayerIndex(layer_index),
                received_detail_level=request.received_detail_level,
                required_topics=tuple(request.required_topics),
                excluded_topics=tuple(request.excluded_topics),
                output_format=request.output_format,
                min_judge_score=JudgeThreshold(request.min_judge_score),
                max_package_length_tokens=request.max_package_length_tokens,
                source_reference_level=request.source_reference_level,
            )
        )
        return layer_body(layer)

    return router
