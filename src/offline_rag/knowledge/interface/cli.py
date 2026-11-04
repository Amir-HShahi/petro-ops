"""Command line entry point for Knowledge Management.

Run `uv run python -m offline_rag.knowledge.interface.cli --help`. The result is
printed to stdout as JSON; errors go to stderr as Problem Details, and log lines
go to stderr as JSON.
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
    ExtractKnowledgeContent,
    ReadPagesWithLvm,
    SubmitKnowledgeItem,
)
from offline_rag.knowledge.application.errors import ExtractedContentNotFoundError
from offline_rag.knowledge.domain.extracted_content import (
    ContentBlockKind,
    ContentSource,
    ExtractedContent,
)
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.domain.version_tag import VersionTag
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
DEFAULT_SHOWN_BLOCKS = 20


def build_parser() -> argparse.ArgumentParser:
    """Return the parser for all Knowledge Management commands."""
    parser = argparse.ArgumentParser(prog="knowledge", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    submit = commands.add_parser(
        "submit", help="Register a DOC, DOCX or PDF file for a Node and extract its content."
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

    extract = commands.add_parser(
        "extract", help="Extract the content of a version again, replacing the old result."
    )
    extract.add_argument("item_id")
    extract.add_argument("--version-tag", default="v1")

    read_pages = commands.add_parser(
        "read-pages", help="Read PDF pages without a text layer with the local LVM."
    )
    read_pages.add_argument("item_id")
    read_pages.add_argument("--version-tag", default="v1")
    read_pages.add_argument(
        "--page",
        type=int,
        action="append",
        help="A page to read, starting at 1. Repeat for more. Default: every page without text.",
    )

    show = commands.add_parser("show-content", help="Print the extracted blocks of a version.")
    show.add_argument("item_id")
    show.add_argument("--version-tag", default="v1")
    show.add_argument("--limit", type=int, default=DEFAULT_SHOWN_BLOCKS, help="Blocks to print.")
    return parser


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    """Run one command and return the process exit code."""
    arguments = build_parser().parse_args(argv)
    settings = settings or Settings()
    configure_logging(settings)
    request_id = uuid.uuid4().hex[:8]
    structlog.contextvars.bind_contextvars(request_id=request_id)
    commands: dict[str, Callable[[argparse.Namespace, KnowledgeWiring], dict[str, Any]]] = {
        "submit": _submit,
        "extract": _extract,
        "read-pages": _read_pages,
        "show-content": _show_content,
    }

    try:
        result = commands[arguments.command](arguments, build_knowledge(settings))
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


def _submit(arguments: argparse.Namespace, knowledge: KnowledgeWiring) -> dict[str, Any]:
    file: Path = arguments.file
    try:
        content = file.read_bytes()
    except OSError as error:
        raise SourceFileNotReadableError(file.name) from error

    item_id = knowledge.submit_handler.submit(
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
    version_tag = VersionTag.for_sequence_number(1)
    try:
        extracted = knowledge.extracted_content_repository.get(item_id, version_tag)
        extraction: dict[str, Any] | None = _summary(extracted, knowledge)
    except ExtractedContentNotFoundError:
        # Registration stands; the failure was logged and `extract` can retry it.
        extraction = None
    return {
        "item_id": item_id,
        "version_tag": version_tag.value,
        "node_id": arguments.node,
        "file_name": file.name,
        "extraction": extraction,
    }


def _extract(arguments: argparse.Namespace, knowledge: KnowledgeWiring) -> dict[str, Any]:
    version_tag = VersionTag(arguments.version_tag)
    extracted = knowledge.extract_handler.extract(
        ExtractKnowledgeContent(item_id=arguments.item_id, version_tag=version_tag)
    )
    return {
        "item_id": arguments.item_id,
        "version_tag": version_tag.value,
        "extraction": _summary(extracted, knowledge),
    }


def _read_pages(arguments: argparse.Namespace, knowledge: KnowledgeWiring) -> dict[str, Any]:
    version_tag = VersionTag(arguments.version_tag)
    content = knowledge.read_pages_handler.read(
        ReadPagesWithLvm(
            item_id=arguments.item_id,
            version_tag=version_tag,
            page_numbers=tuple(arguments.page) if arguments.page else None,
        )
    )
    return {
        "item_id": arguments.item_id,
        "version_tag": version_tag.value,
        "extraction": _summary(content, knowledge),
    }


def _show_content(arguments: argparse.Namespace, knowledge: KnowledgeWiring) -> dict[str, Any]:
    version_tag = VersionTag(arguments.version_tag)
    extracted = knowledge.extracted_content_repository.get(arguments.item_id, version_tag)
    return {
        "item_id": arguments.item_id,
        "version_tag": version_tag.value,
        "extraction": _summary(extracted, knowledge),
        "blocks": [
            {
                "order": block.order,
                "kind": block.kind.value,
                "page_number": block.page_number,
                "heading_path": list(block.heading_path),
                "source": block.source.value,
                "needs_human_review": block.needs_human_review,
                "review_reason": block.review_reason,
                "text": block.text,
            }
            for block in extracted.blocks[: arguments.limit]
        ],
    }


def _summary(extracted: ExtractedContent, knowledge: KnowledgeWiring) -> dict[str, Any]:
    return {
        "document_format": extracted.document_format.value,
        "page_count": extracted.page_count,
        "block_count": len(extracted.blocks),
        "table_count": sum(block.kind == ContentBlockKind.TABLE for block in extracted.blocks),
        "lvm_block_count": sum(block.source == ContentSource.LVM for block in extracted.blocks),
        "blocks_for_review": sum(block.needs_human_review for block in extracted.blocks),
        "pages_without_text": list(
            extracted.pages_without_text(
                min_page_text_chars=knowledge.extract_handler.min_page_text_chars
            )
        ),
    }


def _write_json(stream: TextIO, body: Mapping[str, object]) -> None:
    print(json.dumps(body, ensure_ascii=False), file=stream)


if __name__ == "__main__":
    sys.exit(main())
