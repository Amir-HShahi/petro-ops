"""JSON bodies of Issues, shared by the CLI and later the API."""

from dataclasses import asdict
from typing import Any

from offline_rag.issue.domain.issue import Issue
from offline_rag.shared_kernel.metadata_record import MetadataRecord


def issue_body(issue: Issue) -> dict[str, Any]:
    """Return the Issue with its SubIssues nested as a tree, each level in sibling order."""
    return {
        "issue_id": issue.issue_id,
        "owner_node_id": issue.owner_node_id.value,
        "title": issue.title,
        "description": issue.description,
        "status": issue.status.value,
        "raised_at": issue.raised_at.isoformat(),
        "metadata": _metadata_body(issue.metadata),
        "sub_issues": _children_body(issue, issue.issue_id),
    }


def issue_summary_body(issue: Issue) -> dict[str, Any]:
    """Return the Issue without its descriptions, for lists."""
    return {
        "issue_id": issue.issue_id,
        "title": issue.title,
        "status": issue.status.value,
        "raised_at": issue.raised_at.isoformat(),
        "sub_issue_count": len(issue.sub_issues),
    }


def _children_body(issue: Issue, parent_id: str) -> list[dict[str, Any]]:
    return [
        {
            "sub_issue_id": sub.sub_issue_id,
            "position": sub.position,
            "title": sub.title,
            "description": sub.description,
            "status": sub.status.value,
            "metadata": _metadata_body(sub.metadata),
            "sub_issues": _children_body(issue, sub.sub_issue_id),
        }
        for sub in issue.children_of(parent_id)
    ]


def _metadata_body(metadata: MetadataRecord) -> dict[str, Any]:
    return {
        name: list(value) if isinstance(value, tuple) else value
        for name, value in asdict(metadata).items()
    }
