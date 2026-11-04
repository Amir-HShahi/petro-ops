"""Command line entry point for Knowledge Management.

Run `uv run python -m offline_rag.knowledge.interface.cli --help`. The result is
printed to stdout as JSON; errors go to stderr as Problem Details, and log lines
go to stderr as JSON.
"""

import argparse
import json
import sys
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TextIO

import structlog

from offline_rag.bootstrap import build_submit_knowledge_item_handler, configure_logging
from offline_rag.knowledge.application.commands import SubmitKnowledgeItem
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.interface.errors import SourceFileNotReadableError
from offline_rag.knowledge.interface.problem_details import (
    problem_for_unexpected_error,
    problem_from_error,
)
from offline_rag.settings import Settings
from offline_rag.shared_kernel.errors import ProjectError
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

log = structlog.get_logger()

EXIT_OK = 0
EXIT_FAILED = 1


def build_parser() -> argparse.ArgumentParser:
    """Return the parser for all Knowledge Management commands."""
    parser = argparse.ArgumentParser(prog="knowledge", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    submit = commands.add_parser("submit", help="Register a DOC, DOCX or PDF file for a Node.")
    submit.add_argument("file", type=Path, help="The file to register.")
    submit.add_argument("--node", required=True, help="Id of the owning Node, as in the registry.")
    submit.add_argument(
        "--confidentiality",
        choices=[level.value for level in ConfidentialityLevel],
        default=ConfidentialityLevel.INTERNAL.value,
    )
    submit.add_argument("--usage-scope")
    submit.add_argument("--document-type")
    submit.add_argument("--domain")
    submit.add_argument("--subdomain")
    submit.add_argument("--project")
    submit.add_argument("--author")
    submit.add_argument("--source-reliability")
    submit.add_argument("--tag", action="append", default=[], help="Repeat for more tags.")
    submit.add_argument("--related-issue", action="append", default=[])
    submit.add_argument("--related-executor", action="append", default=[])
    submit.add_argument("--related-rfp", action="append", default=[])
    return parser


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    """Run one command and return the process exit code."""
    arguments = build_parser().parse_args(argv)
    settings = settings or Settings()
    configure_logging(settings)
    request_id = uuid.uuid4().hex[:8]
    structlog.contextvars.bind_contextvars(request_id=request_id)

    try:
        result = _submit(arguments, settings)
    except ProjectError as error:
        log.exception("command_failed", code=error.code)
        _write_json(sys.stderr, problem_from_error(error, request_id=request_id))
        return EXIT_FAILED
    except Exception:
        log.exception("command_failed", code="UNEXPECTED_ERROR")
        _write_json(sys.stderr, problem_for_unexpected_error(request_id=request_id))
        return EXIT_FAILED
    finally:
        structlog.contextvars.unbind_contextvars("request_id")

    _write_json(sys.stdout, result)
    return EXIT_OK


def _submit(arguments: argparse.Namespace, settings: Settings) -> dict[str, str]:
    file: Path = arguments.file
    try:
        content = file.read_bytes()
    except OSError as error:
        raise SourceFileNotReadableError(file.name) from error

    handler = build_submit_knowledge_item_handler(settings)
    item_id = handler.submit(
        SubmitKnowledgeItem(
            owner_node_id=NodeIdentifier(arguments.node),
            source_file_name=file.name,
            content=content,
            scope=KnowledgeScope(
                confidentiality=ConfidentialityLevel(arguments.confidentiality),
                usage_scope=arguments.usage_scope,
            ),
            metadata=MetadataRecord(
                domain=arguments.domain,
                subdomain=arguments.subdomain,
                project=arguments.project,
                author=arguments.author,
                document_type=arguments.document_type,
                related_issue_ids=tuple(arguments.related_issue),
                related_executor_ids=tuple(arguments.related_executor),
                related_rfp_ids=tuple(arguments.related_rfp),
                tags=tuple(arguments.tag),
                source_reliability=arguments.source_reliability,
            ),
        )
    )
    return {"item_id": item_id, "node_id": arguments.node, "file_name": file.name}


def _write_json(stream: TextIO, body: Mapping[str, object]) -> None:
    print(json.dumps(body, ensure_ascii=False), file=stream)


if __name__ == "__main__":
    sys.exit(main())
