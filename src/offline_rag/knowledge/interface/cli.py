"""Command line entry point for Knowledge Management.

Run `uv run knowledge --help`. Results are printed to stdout as JSON; errors go to
stderr as Problem Details, and log lines go to stderr as JSON. The `run` commands
start long-running processes: the workers, the outbox relay and the API.
"""

import argparse
import json
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO

import structlog

from offline_rag.bootstrap import KnowledgeWiring, build_knowledge, configure_logging
from offline_rag.knowledge.application.commands import (
    PublishKnowledgeVersion,
    ReingestKnowledgeItem,
    SubmitKnowledgeItem,
)
from offline_rag.knowledge.application.ports import IngestionLane
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.interface.api import run_api
from offline_rag.knowledge.interface.errors import SourceFileNotReadableError
from offline_rag.knowledge.interface.ingestion_worker import run_worker
from offline_rag.knowledge.interface.outbox_relay import run_relay
from offline_rag.knowledge.interface.problem_details import (
    problem_for_unexpected_error,
    problem_from_error,
)
from offline_rag.knowledge.interface.response_bodies import (
    chunks_body,
    content_body,
    ingestion_status_body,
    receipt_body,
)
from offline_rag.settings import Settings
from offline_rag.shared_kernel.errors import ProjectError
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

log = structlog.get_logger()

EXIT_OK = 0
EXIT_FAILED = 1
DEFAULT_SHOWN_BLOCKS = 20
DEFAULT_SHOWN_CHUNKS = 20

Command = Callable[[argparse.Namespace, KnowledgeWiring, Settings], dict[str, Any]]


def build_parser() -> argparse.ArgumentParser:
    """Return the parser for all Knowledge Management commands."""
    parser = argparse.ArgumentParser(prog="knowledge", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    submit = commands.add_parser(
        "submit", help="Register a DOC, DOCX or PDF file for a Node and queue its ingestion."
    )
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

    publish = commands.add_parser(
        "publish-version",
        help="Publish a new file as the next, active version of an item and queue its ingestion.",
    )
    publish.add_argument("item_id")
    publish.add_argument("file", type=Path, help="The new file.")
    publish.add_argument("--change-reason", required=True, help="Why the item changed.")
    publish.add_argument("--diff-summary", help="A short summary of what changed.")

    status = commands.add_parser("status", help="Print the status of an ingestion.")
    status.add_argument("ingestion_id")

    show = commands.add_parser("show-content", help="Print the extracted blocks of a version.")
    show.add_argument("item_id")
    show.add_argument("--version", dest="version_tag", help="Default: the active version.")
    show.add_argument("--limit", type=int, default=DEFAULT_SHOWN_BLOCKS, help="Blocks to print.")

    chunks = commands.add_parser("show-chunks", help="Print the chunks of a version.")
    chunks.add_argument("item_id")
    chunks.add_argument("--version", dest="version_tag", help="Default: the active version.")
    chunks.add_argument("--limit", type=int, default=DEFAULT_SHOWN_CHUNKS, help="Chunks to print.")

    reingest = commands.add_parser(
        "reingest", help="Queue a version for ingestion again, replacing its content."
    )
    reingest.add_argument("item_id")
    reingest.add_argument("--version", dest="version_tag", help="Default: the active version.")

    worker = commands.add_parser("worker", help="Ingestion workers.")
    worker_run = worker.add_subparsers(dest="action", required=True).add_parser(
        "run", help="Run the steps of one lane until stopped (ADR 0005)."
    )
    worker_run.add_argument("--lane", required=True, choices=[lane.value for lane in IngestionLane])

    relay = commands.add_parser("relay", help="The outbox relay.")
    relay.add_subparsers(dest="action", required=True).add_parser(
        "run", help="Publish outbox messages and resend lost ones until stopped."
    )

    api = commands.add_parser("api", help="The ingestion API.")
    api.add_subparsers(dest="action", required=True).add_parser(
        "run", help="Serve the API on API_HOST:API_PORT until stopped (ADR 0006)."
    )
    return parser


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    """Run one command and return the process exit code."""
    arguments = build_parser().parse_args(argv)
    settings = settings or Settings()
    match arguments.command:
        case "worker":
            run_worker(IngestionLane(arguments.lane), settings)
            return EXIT_OK
        case "relay":
            run_relay(settings)
            return EXIT_OK
        case "api":
            run_api(settings)
            return EXIT_OK
    return _run_command(arguments, settings)


def run() -> None:
    """Run the `knowledge` console script."""
    sys.exit(main())


def _run_command(arguments: argparse.Namespace, settings: Settings) -> int:
    configure_logging(settings)
    request_id = uuid.uuid4().hex[:8]
    structlog.contextvars.bind_contextvars(request_id=request_id)
    commands: dict[str, Command] = {
        "submit": _submit,
        "publish-version": _publish_version,
        "status": _status,
        "show-content": _show_content,
        "show-chunks": _show_chunks,
        "reingest": _reingest,
    }

    knowledge: KnowledgeWiring | None = None
    try:
        knowledge = build_knowledge(settings)
        result = commands[arguments.command](arguments, knowledge, settings)
    except ProjectError as error:
        log.exception("command_failed", code=error.code)
        _write_json(sys.stderr, problem_from_error(error, request_id=request_id))
        return EXIT_FAILED
    except Exception:
        log.exception("command_failed", code="UNEXPECTED_ERROR")
        _write_json(sys.stderr, problem_for_unexpected_error(request_id=request_id))
        return EXIT_FAILED
    finally:
        if knowledge is not None:
            knowledge.close()
        structlog.contextvars.unbind_contextvars("request_id")

    _write_json(sys.stdout, result)
    return EXIT_OK


def _read_file(file: Path) -> bytes:
    try:
        return file.read_bytes()
    except OSError as error:
        raise SourceFileNotReadableError(file.name) from error


def _submit(
    arguments: argparse.Namespace, knowledge: KnowledgeWiring, settings: Settings
) -> dict[str, Any]:
    file: Path = arguments.file
    content = _read_file(file)
    receipt = knowledge.submit_handler.submit(
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
            request_id=_request_id(),
        )
    )
    return receipt_body(receipt)


def _publish_version(
    arguments: argparse.Namespace, knowledge: KnowledgeWiring, settings: Settings
) -> dict[str, Any]:
    file: Path = arguments.file
    receipt = knowledge.publish_version_handler.publish(
        PublishKnowledgeVersion(
            item_id=arguments.item_id,
            source_file_name=file.name,
            content=_read_file(file),
            change_reason=arguments.change_reason,
            diff_summary=arguments.diff_summary,
            request_id=_request_id(),
        )
    )
    return receipt_body(receipt)


def _status(
    arguments: argparse.Namespace, knowledge: KnowledgeWiring, settings: Settings
) -> dict[str, Any]:
    return ingestion_status_body(knowledge.queries.get_ingestion(arguments.ingestion_id))


def _show_content(
    arguments: argparse.Namespace, knowledge: KnowledgeWiring, settings: Settings
) -> dict[str, Any]:
    version_tag, extracted = knowledge.queries.get_content(
        arguments.item_id, _version_tag(arguments)
    )
    return content_body(
        arguments.item_id,
        version_tag,
        extracted,
        min_page_text_chars=settings.min_page_text_chars,
        limit=arguments.limit,
    )


def _show_chunks(
    arguments: argparse.Namespace, knowledge: KnowledgeWiring, settings: Settings
) -> dict[str, Any]:
    found = knowledge.queries.get_chunks(arguments.item_id, _version_tag(arguments))
    return chunks_body(arguments.item_id, found, limit=arguments.limit)


def _reingest(
    arguments: argparse.Namespace, knowledge: KnowledgeWiring, settings: Settings
) -> dict[str, Any]:
    receipt = knowledge.reingest_handler.reingest(
        ReingestKnowledgeItem(
            item_id=arguments.item_id,
            version_tag=_version_tag(arguments),
            request_id=_request_id(),
        )
    )
    return receipt_body(receipt)


def _version_tag(arguments: argparse.Namespace) -> VersionTag | None:
    return VersionTag(arguments.version_tag) if arguments.version_tag else None


def _request_id() -> str | None:
    bound: str | None = structlog.contextvars.get_contextvars().get("request_id")
    return bound


def _write_json(stream: TextIO, body: Mapping[str, object]) -> None:
    print(json.dumps(body, ensure_ascii=False), file=stream)


if __name__ == "__main__":
    sys.exit(main())
