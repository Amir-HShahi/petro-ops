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
from offline_rag.issue.application.commands import (
    AcceptSubIssueCandidates,
    AddSubIssue,
    AddSubIssueDependency,
    ChangeIssueStatus,
    DecomposeIssue,
    MoveSubIssue,
    RaiseIssue,
    RemoveSubIssueDependency,
    ResolveIssue,
    SetIssuePriority,
)
from offline_rag.issue.domain.issue_priority import IssuePriority
from offline_rag.issue.domain.issue_status import IssueStatus
from offline_rag.issue.interface.response_bodies import (
    candidate_body,
    issue_body,
    issue_summary_body,
)

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
    _add_metadata_arguments(raise_command)

    add_sub_issue = commands.add_parser(
        "add-sub-issue",
        help="Split a part off an Issue, or off one of its SubIssues; it goes last.",
    )
    add_sub_issue.add_argument("issue_id", help="The Issue to split.")
    add_sub_issue.add_argument(
        "--parent", help="Id of the SubIssue to split further. Leave out to split the Issue."
    )
    add_sub_issue.add_argument("--title", required=True)
    add_sub_issue.add_argument("--description", required=True)
    _add_metadata_arguments(add_sub_issue)

    decompose = commands.add_parser(
        "decompose",
        help="Ask the local LLM to suggest SubIssues, citing the KnowledgeItems given. "
        "The suggestions wait as numbered candidates; nothing is added yet.",
    )
    decompose.add_argument("issue_id", help="The Issue to split.")
    decompose.add_argument(
        "--knowledge-item",
        action="append",
        required=True,
        help="Id of a KnowledgeItem the LLM reads and cites. Repeat for more items.",
    )

    accept = commands.add_parser(
        "accept-sub-issue-candidates",
        help="Turn chosen candidates into SubIssues of the Issue, in the order given.",
    )
    accept.add_argument("issue_id", help="The Issue the candidates belong to.")
    accept.add_argument("numbers", type=int, nargs="+", help="Candidate numbers, such as 1 3.")

    set_priority = commands.add_parser("set-priority", help="Say how urgent an Issue is.")
    set_priority.add_argument("issue_id")
    set_priority.add_argument("priority", choices=[priority.value for priority in IssuePriority])

    move = commands.add_parser(
        "move-sub-issue", help="Move a SubIssue to another place among its siblings."
    )
    move.add_argument("issue_id")
    move.add_argument("sub_issue_id")
    move.add_argument("--position", type=int, required=True, help="The new place, from 1.")

    for name, help_text in (
        ("add-dependency", "Make a SubIssue wait for another SubIssue of the same Issue."),
        ("remove-dependency", "Stop a SubIssue waiting for another SubIssue."),
    ):
        dependency = commands.add_parser(name, help=help_text)
        dependency.add_argument("issue_id")
        dependency.add_argument("sub_issue_id", help="The SubIssue that waits.")
        dependency.add_argument("--on", required=True, help="The SubIssue it waits for.")

    change_status = commands.add_parser(
        "change-status",
        help="Move an Issue, or one of its SubIssues, to another status. Use `resolve` "
        "to resolve the Issue itself.",
    )
    change_status.add_argument("issue_id")
    change_status.add_argument("status", choices=[status.value for status in IssueStatus])
    change_status.add_argument("--sub-issue", help="The SubIssue to change, not the Issue.")

    resolve = commands.add_parser(
        "resolve", help="Mark an Issue resolved once every SubIssue is closed."
    )
    resolve.add_argument("issue_id")
    resolve.add_argument("--summary", required=True, help="How the problem was solved.")

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
        "add-sub-issue": _add_sub_issue,
        "decompose": _decompose_issue,
        "accept-sub-issue-candidates": _accept_sub_issue_candidates,
        "set-priority": _set_priority,
        "move-sub-issue": _move_sub_issue,
        "add-dependency": _add_dependency,
        "remove-dependency": _remove_dependency,
        "change-status": _change_status,
        "resolve": _resolve,
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


def _add_metadata_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--domain", help="Metadata: the domain, such as asset integrity.")
    parser.add_argument("--subdomain")
    parser.add_argument("--project")
    parser.add_argument(
        "--tag", action="append", default=[], help="Metadata tag. Repeat for more tags."
    )


def _metadata(arguments: argparse.Namespace) -> MetadataRecord:
    return MetadataRecord(
        domain=arguments.domain,
        subdomain=arguments.subdomain,
        project=arguments.project,
        tags=tuple(arguments.tag),
    )


def _raise_issue(arguments: argparse.Namespace, issue: IssueWiring) -> dict[str, Any]:
    raised = issue.raise_issue_handler.raise_issue(
        RaiseIssue(
            owner_node_id=NodeIdentifier(arguments.node),
            title=arguments.title,
            description=arguments.description,
            metadata=_metadata(arguments),
        )
    )
    return issue_body(raised)


def _add_sub_issue(arguments: argparse.Namespace, issue: IssueWiring) -> dict[str, Any]:
    split, added = issue.add_sub_issue_handler.add_sub_issue(
        AddSubIssue(
            issue_id=arguments.issue_id,
            parent_id=arguments.parent,
            title=arguments.title,
            description=arguments.description,
            metadata=_metadata(arguments),
        )
    )
    return {"added_sub_issue_id": added.sub_issue_id} | issue_body(split)


def _decompose_issue(arguments: argparse.Namespace, issue: IssueWiring) -> dict[str, Any]:
    result = issue.decompose_issue_handler.decompose(
        DecomposeIssue(
            issue_id=arguments.issue_id,
            knowledge_item_ids=tuple(arguments.knowledge_item),
        )
    )
    return {
        "issue_id": result.issue.issue_id,
        "candidates": [candidate_body(candidate) for candidate in result.candidates],
        "missing_information": result.missing_information,
        "dropped_citation_count": result.dropped_citation_count,
    }


def _accept_sub_issue_candidates(
    arguments: argparse.Namespace, issue: IssueWiring
) -> dict[str, Any]:
    accepted = issue.accept_sub_issue_candidates_handler.accept(
        AcceptSubIssueCandidates(issue_id=arguments.issue_id, numbers=tuple(arguments.numbers))
    )
    return issue_body(accepted)


def _set_priority(arguments: argparse.Namespace, issue: IssueWiring) -> dict[str, Any]:
    return issue_body(
        issue.set_priority_handler.set_priority(
            SetIssuePriority(
                issue_id=arguments.issue_id, priority=IssuePriority(arguments.priority)
            )
        )
    )


def _move_sub_issue(arguments: argparse.Namespace, issue: IssueWiring) -> dict[str, Any]:
    return issue_body(
        issue.move_sub_issue_handler.move(
            MoveSubIssue(
                issue_id=arguments.issue_id,
                sub_issue_id=arguments.sub_issue_id,
                position=arguments.position,
            )
        )
    )


def _add_dependency(arguments: argparse.Namespace, issue: IssueWiring) -> dict[str, Any]:
    return issue_body(
        issue.add_dependency_handler.add(
            AddSubIssueDependency(
                issue_id=arguments.issue_id,
                sub_issue_id=arguments.sub_issue_id,
                depends_on_sub_issue_id=arguments.on,
            )
        )
    )


def _remove_dependency(arguments: argparse.Namespace, issue: IssueWiring) -> dict[str, Any]:
    return issue_body(
        issue.remove_dependency_handler.remove(
            RemoveSubIssueDependency(
                issue_id=arguments.issue_id,
                sub_issue_id=arguments.sub_issue_id,
                depends_on_sub_issue_id=arguments.on,
            )
        )
    )


def _change_status(arguments: argparse.Namespace, issue: IssueWiring) -> dict[str, Any]:
    return issue_body(
        issue.change_status_handler.change(
            ChangeIssueStatus(
                issue_id=arguments.issue_id,
                status=IssueStatus(arguments.status),
                sub_issue_id=arguments.sub_issue,
            )
        )
    )


def _resolve(arguments: argparse.Namespace, issue: IssueWiring) -> dict[str, Any]:
    return issue_body(
        issue.resolve_issue_handler.resolve(
            ResolveIssue(issue_id=arguments.issue_id, resolution_summary=arguments.summary)
        )
    )


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
