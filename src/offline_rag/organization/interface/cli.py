"""Command line entry point for Organizational Hierarchy.

Run `uv run organization --help`. Results are printed to stdout as JSON; errors go
to stderr as Problem Details, and log lines go to stderr as JSON.
"""

import argparse
import json
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO

import structlog

from offline_rag.bootstrap import OrganizationWiring, build_organization, configure_logging

# The Problem Details helpers depend only on the shared error categories, so every
# context's entry points share them.
from offline_rag.knowledge.interface.problem_details import (
    problem_for_unexpected_error,
    problem_from_error,
)
from offline_rag.organization.application.commands import DefineTransferRule, RegisterNode
from offline_rag.organization.application.errors import NodeAlreadyRegisteredError
from offline_rag.organization.domain.layer import Layer
from offline_rag.organization.domain.node import Node
from offline_rag.organization.domain.transfer_detail_level import TransferDetailLevel
from offline_rag.organization.interface.node_registry_file import read_node_registry
from offline_rag.settings import Settings
from offline_rag.shared_kernel.confidentiality_level import ConfidentialityLevel
from offline_rag.shared_kernel.errors import ProjectError
from offline_rag.shared_kernel.judge_threshold import (
    DEFAULT_JUDGE_THRESHOLD_POINTS,
    JudgeThreshold,
)
from offline_rag.shared_kernel.layer_index import LayerIndex
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

log = structlog.get_logger()

EXIT_OK = 0
EXIT_FAILED = 1

Command = Callable[[argparse.Namespace, OrganizationWiring, Settings], dict[str, Any]]


def build_parser() -> argparse.ArgumentParser:
    """Return the parser for all Organizational Hierarchy commands."""
    parser = argparse.ArgumentParser(prog="organization", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    register = commands.add_parser("register-node", help="Add a Node to its Layer.")
    register.add_argument("node_id", help="Stable id, such as sp12_inspection_team.")
    register.add_argument("--name", required=True)
    register.add_argument("--layer", type=int, required=True, help="0 (strategic) to 4.")
    register.add_argument("--parent", help="Id of the parent Node; leave out only in Layer 0.")
    register.add_argument("--activity-area", required=True)
    register.add_argument("--reporting-rule", required=True, help="Such as weekly.")
    register.add_argument(
        "--confidentiality",
        choices=[level.value for level in ConfidentialityLevel],
        default=ConfidentialityLevel.INTERNAL.value,
    )
    register.add_argument(
        "--track-internal-structure",
        action="store_true",
        help="Model this Node's children; without it, the Node cannot have children.",
    )

    import_nodes = commands.add_parser(
        "import-nodes",
        help="Register every Node of a registry CSV that is not registered yet.",
    )
    import_nodes.add_argument(
        "--file", type=Path, help="Default: NODE_REGISTRY_PATH, the case-study registry."
    )

    define_rule = commands.add_parser(
        "define-transfer-rule",
        help="Set what a Layer requires of the TransferPackages it receives (spec §10.1).",
    )
    define_rule.add_argument("layer", type=int, help="The receiving Layer, 0 to 3.")
    define_rule.add_argument(
        "--detail-level", required=True, choices=[level.value for level in TransferDetailLevel]
    )
    define_rule.add_argument(
        "--required-topic", action="append", default=[], help="Repeat for more topics."
    )
    define_rule.add_argument(
        "--excluded-topic", action="append", default=[], help="Repeat for more topics."
    )
    define_rule.add_argument("--output-format", required=True, help="Such as markdown.")
    define_rule.add_argument(
        "--min-judge-score",
        type=int,
        default=DEFAULT_JUDGE_THRESHOLD_POINTS,
        help="Points out of 20. Default: %(default)s.",
    )
    define_rule.add_argument("--max-package-length-tokens", type=int, required=True)
    define_rule.add_argument("--source-reference-level", required=True, help="Such as page.")
    return parser


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    """Run one command and return the process exit code."""
    arguments = build_parser().parse_args(argv)
    settings = settings or Settings()
    configure_logging(settings)
    request_id = uuid.uuid4().hex[:8]
    structlog.contextvars.bind_contextvars(request_id=request_id)
    commands: dict[str, Command] = {
        "register-node": _register_node,
        "import-nodes": _import_nodes,
        "define-transfer-rule": _define_transfer_rule,
    }

    organization: OrganizationWiring | None = None
    try:
        organization = build_organization(settings)
        result = commands[arguments.command](arguments, organization, settings)
    except ProjectError as error:
        log.exception("command_failed", code=error.code)
        _write_json(sys.stderr, problem_from_error(error, request_id=request_id))
        return EXIT_FAILED
    except Exception:
        log.exception("command_failed", code="UNEXPECTED_ERROR")
        _write_json(sys.stderr, problem_for_unexpected_error(request_id=request_id))
        return EXIT_FAILED
    finally:
        if organization is not None:
            organization.close()
        structlog.contextvars.unbind_contextvars("request_id")

    _write_json(sys.stdout, result)
    return EXIT_OK


def run() -> None:
    """Run the `organization` console script."""
    sys.exit(main())


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


def _register_node(
    arguments: argparse.Namespace, organization: OrganizationWiring, settings: Settings
) -> dict[str, Any]:
    node = organization.register_node_handler.register(
        RegisterNode(
            node_id=NodeIdentifier(arguments.node_id),
            name=arguments.name,
            layer_index=LayerIndex(arguments.layer),
            parent_node_id=NodeIdentifier(arguments.parent) if arguments.parent else None,
            activity_area=arguments.activity_area,
            reporting_rule=arguments.reporting_rule,
            confidentiality=ConfidentialityLevel(arguments.confidentiality),
            is_internal_structure_tracked=arguments.track_internal_structure,
        )
    )
    return node_body(node)


def _import_nodes(
    arguments: argparse.Namespace, organization: OrganizationWiring, settings: Settings
) -> dict[str, Any]:
    path: Path = arguments.file or settings.node_registry_path
    registered: list[str] = []
    already_registered: list[str] = []
    for command in read_node_registry(path):
        try:
            organization.register_node_handler.register(command)
        except NodeAlreadyRegisteredError:
            # Importing the same file again is safe: known Nodes are left as they are.
            already_registered.append(command.node_id.value)
            continue
        registered.append(command.node_id.value)
    return {"registered": registered, "already_registered": already_registered}


def _define_transfer_rule(
    arguments: argparse.Namespace, organization: OrganizationWiring, settings: Settings
) -> dict[str, Any]:
    layer = organization.define_transfer_rule_handler.define(
        DefineTransferRule(
            layer_index=LayerIndex(arguments.layer),
            received_detail_level=TransferDetailLevel(arguments.detail_level),
            required_topics=tuple(arguments.required_topic),
            excluded_topics=tuple(arguments.excluded_topic),
            output_format=arguments.output_format,
            min_judge_score=JudgeThreshold(arguments.min_judge_score),
            max_package_length_tokens=arguments.max_package_length_tokens,
            source_reference_level=arguments.source_reference_level,
        )
    )
    return layer_body(layer)


def _write_json(stream: TextIO, body: Mapping[str, object]) -> None:
    print(json.dumps(body, ensure_ascii=False), file=stream)


if __name__ == "__main__":
    sys.exit(main())
