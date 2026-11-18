"""Issue Management routes for the pipeline page (ADR 0013).

The routes call the same handlers and queries as the `issue` CLI and return the same
bodies. Errors are raised as project errors; the app that mounts the router turns
them into Problem Details (ADR 0011).
"""

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from offline_rag.issue.application.accept_sub_issue_candidates import (
    AcceptSubIssueCandidatesHandler,
)
from offline_rag.issue.application.add_sub_issue import AddSubIssueHandler
from offline_rag.issue.application.add_sub_issue_dependency import AddSubIssueDependencyHandler
from offline_rag.issue.application.change_issue_status import ChangeIssueStatusHandler
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
from offline_rag.issue.application.decompose_issue import DecomposeIssueHandler
from offline_rag.issue.application.issue_queries import IssueQueries
from offline_rag.issue.application.move_sub_issue import MoveSubIssueHandler
from offline_rag.issue.application.raise_issue import RaiseIssueHandler
from offline_rag.issue.application.remove_sub_issue_dependency import (
    RemoveSubIssueDependencyHandler,
)
from offline_rag.issue.application.resolve_issue import ResolveIssueHandler
from offline_rag.issue.application.set_issue_priority import SetIssuePriorityHandler
from offline_rag.issue.domain.issue_priority import IssuePriority
from offline_rag.issue.domain.issue_status import IssueStatus
from offline_rag.issue.interface.response_bodies import (
    candidate_body,
    issue_body,
    issue_summary_body,
)
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

CREATED = 201


@dataclass(frozen=True, kw_only=True)
class IssueRouteHandlers:
    """The Issue Management use cases and queries the routes call."""

    raise_issue: RaiseIssueHandler
    add_sub_issue: AddSubIssueHandler
    decompose_issue: DecomposeIssueHandler
    accept_sub_issue_candidates: AcceptSubIssueCandidatesHandler
    set_priority: SetIssuePriorityHandler
    move_sub_issue: MoveSubIssueHandler
    add_dependency: AddSubIssueDependencyHandler
    remove_dependency: RemoveSubIssueDependencyHandler
    change_status: ChangeIssueStatusHandler
    resolve_issue: ResolveIssueHandler
    queries: IssueQueries


class RaiseIssueRequest(BaseModel):
    """The body of `POST /issues`."""

    owner_node_id: str
    title: str
    description: str
    domain: str | None = None
    tags: list[str] = Field(default_factory=list)


class AddSubIssueRequest(BaseModel):
    """The body of `POST /issues/{issue_id}/sub-issues`."""

    parent_id: str | None = None
    title: str
    description: str


class DecomposeIssueRequest(BaseModel):
    """The body of `POST /issues/{issue_id}/decompositions`."""

    knowledge_item_ids: list[str]


class AcceptCandidatesRequest(BaseModel):
    """The body of `POST /issues/{issue_id}/candidates/accepted`."""

    numbers: list[int]


class PriorityRequest(BaseModel):
    """The body of `PUT /issues/{issue_id}/priority`."""

    priority: IssuePriority


class PositionRequest(BaseModel):
    """The body of `PUT /issues/{issue_id}/sub-issues/{sub_issue_id}/position`."""

    position: int


class DependencyRequest(BaseModel):
    """The body of `POST /issues/{issue_id}/sub-issues/{sub_issue_id}/dependencies`."""

    depends_on_sub_issue_id: str


class StatusRequest(BaseModel):
    """The body of `PUT /issues/{issue_id}/status`."""

    status: IssueStatus
    sub_issue_id: str | None = None


class ResolutionRequest(BaseModel):
    """The body of `POST /issues/{issue_id}/resolution`."""

    resolution_summary: str


def create_issue_router(handlers: IssueRouteHandlers) -> APIRouter:
    """Return the routes over the Issue Management use cases and queries."""
    router = APIRouter(prefix="/issues", tags=["issue"])

    @router.get("")
    def list_issues(node: str) -> dict[str, Any]:
        """Return the Issues of a Node, oldest first."""
        node_id = NodeIdentifier(node)
        return {
            "owner_node_id": node_id.value,
            "issues": [
                issue_summary_body(issue) for issue in handlers.queries.list_by_owner(node_id)
            ],
        }

    @router.post("", status_code=CREATED)
    def raise_issue(request: RaiseIssueRequest) -> dict[str, Any]:
        """Raise an Issue for a registered Node, flagging the Node's Issues it looks like."""
        return issue_body(
            handlers.raise_issue.raise_issue(
                RaiseIssue(
                    owner_node_id=NodeIdentifier(request.owner_node_id),
                    title=request.title,
                    description=request.description,
                    metadata=MetadataRecord(domain=request.domain, tags=tuple(request.tags)),
                )
            )
        )

    @router.get("/{issue_id}")
    def show_issue(issue_id: str) -> dict[str, Any]:
        """Return an Issue with its SubIssue tree, flags and candidates."""
        return issue_body(handlers.queries.get(issue_id))

    @router.post("/{issue_id}/sub-issues", status_code=CREATED)
    def add_sub_issue(issue_id: str, request: AddSubIssueRequest) -> dict[str, Any]:
        """Split a part off the Issue, or off one of its SubIssues; it goes last."""
        issue, added = handlers.add_sub_issue.add_sub_issue(
            AddSubIssue(
                issue_id=issue_id,
                parent_id=request.parent_id,
                title=request.title,
                description=request.description,
                metadata=MetadataRecord(),
            )
        )
        return {"added_sub_issue_id": added.sub_issue_id} | issue_body(issue)

    @router.post("/{issue_id}/decompositions")
    def decompose_issue(issue_id: str, request: DecomposeIssueRequest) -> dict[str, Any]:
        """Ask the local LLM for SubIssue candidates citing the KnowledgeItems given.

        The answer takes about a minute; the request waits for it.
        """
        result = handlers.decompose_issue.decompose(
            DecomposeIssue(issue_id=issue_id, knowledge_item_ids=tuple(request.knowledge_item_ids))
        )
        return {
            "issue_id": result.issue.issue_id,
            "candidates": [candidate_body(candidate) for candidate in result.candidates],
            "missing_information": result.missing_information,
            "dropped_citation_count": result.dropped_citation_count,
        }

    @router.post("/{issue_id}/candidates/accepted")
    def accept_candidates(issue_id: str, request: AcceptCandidatesRequest) -> dict[str, Any]:
        """Turn the chosen candidates into SubIssues, in the order given."""
        return issue_body(
            handlers.accept_sub_issue_candidates.accept(
                AcceptSubIssueCandidates(issue_id=issue_id, numbers=tuple(request.numbers))
            )
        )

    @router.put("/{issue_id}/priority")
    def set_priority(issue_id: str, request: PriorityRequest) -> dict[str, Any]:
        """Say how urgent the Issue is."""
        return issue_body(
            handlers.set_priority.set_priority(
                SetIssuePriority(issue_id=issue_id, priority=request.priority)
            )
        )

    @router.put("/{issue_id}/sub-issues/{sub_issue_id}/position")
    def move_sub_issue(
        issue_id: str, sub_issue_id: str, request: PositionRequest
    ) -> dict[str, Any]:
        """Move a SubIssue to another place among its siblings."""
        return issue_body(
            handlers.move_sub_issue.move(
                MoveSubIssue(
                    issue_id=issue_id, sub_issue_id=sub_issue_id, position=request.position
                )
            )
        )

    @router.post("/{issue_id}/sub-issues/{sub_issue_id}/dependencies")
    def add_dependency(
        issue_id: str, sub_issue_id: str, request: DependencyRequest
    ) -> dict[str, Any]:
        """Make a SubIssue wait for another SubIssue of the same Issue."""
        return issue_body(
            handlers.add_dependency.add(
                AddSubIssueDependency(
                    issue_id=issue_id,
                    sub_issue_id=sub_issue_id,
                    depends_on_sub_issue_id=request.depends_on_sub_issue_id,
                )
            )
        )

    @router.delete("/{issue_id}/sub-issues/{sub_issue_id}/dependencies/{depends_on_sub_issue_id}")
    def remove_dependency(
        issue_id: str, sub_issue_id: str, depends_on_sub_issue_id: str
    ) -> dict[str, Any]:
        """Stop a SubIssue waiting for another SubIssue."""
        return issue_body(
            handlers.remove_dependency.remove(
                RemoveSubIssueDependency(
                    issue_id=issue_id,
                    sub_issue_id=sub_issue_id,
                    depends_on_sub_issue_id=depends_on_sub_issue_id,
                )
            )
        )

    @router.put("/{issue_id}/status")
    def change_status(issue_id: str, request: StatusRequest) -> dict[str, Any]:
        """Move the Issue, or one of its SubIssues, to another status."""
        return issue_body(
            handlers.change_status.change(
                ChangeIssueStatus(
                    issue_id=issue_id, status=request.status, sub_issue_id=request.sub_issue_id
                )
            )
        )

    @router.post("/{issue_id}/resolution")
    def resolve_issue(issue_id: str, request: ResolutionRequest) -> dict[str, Any]:
        """Mark the Issue resolved once every SubIssue is closed."""
        return issue_body(
            handlers.resolve_issue.resolve(
                ResolveIssue(issue_id=issue_id, resolution_summary=request.resolution_summary)
            )
        )

    return router
