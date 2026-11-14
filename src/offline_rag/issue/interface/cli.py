"""Command line entry point for Issue Management.

Run `uv run issue --help`. Results are printed to stdout as JSON; errors go to
stderr as Problem Details, and log lines go to stderr as JSON.
"""

import argparse
import json
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TextIO

import structlog

from offline_rag.bootstrap import IssueWiring, build_issue, configure_logging
from offline_rag.issue.application.commands import RaiseIssue
from offline_rag.issue.interface.response_bodies import issue_body, issue_summary_body

# The Problem Details helpers depend only on the shared error categories, so every
# context's entry points share them.
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

Command = Callable[[argparse.Namespace, IssueWiring], dict[str, Any]]


def build_parser() -> argparse.ArgumentParser:
    """Return the parser for all Issue Management commands."""
    parser = argparse.ArgumentParser(prog="issue", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    raise_command = commands.add_parser("raise", help="Define a new Issue for a Node.")
    raise_command.add_argument("--node", required=True, help="Id of the owner Node.")
    raise_command.add_argument("--title", required=True)
    raise_command.add_argument("--description", required=True)
    raise_command.add_argument("--domain", help="Metadata: the domain, such as asset integrity.")
    raise_command.add_argument("--subdomain")
    raise_command.add_argument("--project")
    raise_command.add_argument(
        "--tag", action="append", default=[], help="Metadata tag. Repeat for more tags."
    )

    show = commands.add_parser("show", help="Print an Issue with its SubIssue tree.")
    show.add_argument("issue_id", help="The id that `issue raise` printed.")

    list_command = commands.add_parser("list", help="List the Issues of a Node, oldest first.")
    list_command.add_argument("--node", required=True, help="Id of the owner Node.")
    return parser


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    """Run one command and return the process exit code."""
    arguments = build_parser().parse_args(argv)
    settings = settings or Settings()
    configure_logging(settings)
    request_id = uuid.uuid4().hex[:8]
    structlog.contextvars.bind_contextvars(request_id=request_id)
    commands: dict[str, Command] = {
        "raise": _raise_issue,
        "show": _show_issue,
        "list": _list_issues,
    }

    issue: IssueWiring | None = None
    try:
        issue = build_issue(settings)
        result = commands[arguments.command](arguments, issue)
    except ProjectError as error:
        log.exception("command_failed", code=error.code)
        _write_json(sys.stderr, problem_from_error(error, request_id=request_id))
        return EXIT_FAILED
    except Exception:
        log.exception("command_failed", code="UNEXPECTED_ERROR")
        _write_json(sys.stderr, problem_for_unexpected_error(request_id=request_id))
        return EXIT_FAILED
    finally:
        if issue is not None:
            issue.close()
        structlog.contextvars.unbind_contextvars("request_id")

    _write_json(sys.stdout, result)
    return EXIT_OK


def run() -> None:
    """Run the `issue` console script."""
    sys.exit(main())


def _raise_issue(arguments: argparse.Namespace, issue: IssueWiring) -> dict[str, Any]:
    raised = issue.raise_issue_handler.raise_issue(
        RaiseIssue(
            owner_node_id=NodeIdentifier(arguments.node),
            title=arguments.title,
            description=arguments.description,
            metadata=MetadataRecord(
                domain=arguments.domain,
                subdomain=arguments.subdomain,
                project=arguments.project,
                tags=tuple(arguments.tag),
            ),
        )
    )
    return issue_body(raised)


def _show_issue(arguments: argparse.Namespace, issue: IssueWiring) -> dict[str, Any]:
    return issue_body(issue.queries.get(arguments.issue_id))


def _list_issues(arguments: argparse.Namespace, issue: IssueWiring) -> dict[str, Any]:
    node_id = NodeIdentifier(arguments.node)
    return {
        "owner_node_id": node_id.value,
        "issues": [issue_summary_body(found) for found in issue.queries.list_by_owner(node_id)],
    }


def _write_json(stream: TextIO, body: Mapping[str, object]) -> None:
    print(json.dumps(body, ensure_ascii=False), file=stream)


if __name__ == "__main__":
    sys.exit(main())
