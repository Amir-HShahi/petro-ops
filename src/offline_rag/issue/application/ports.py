"""Ports of Issue Management: what its use cases need from the outside."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from offline_rag.issue.domain.issue import Issue
from offline_rag.shared_kernel.domain_event import DomainEvent
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


class IssueRepository(Protocol):
    """Stores Issues together with their SubIssues (docs/domain-model.md, section 11)."""

    def get_by_id(self, issue_id: str) -> Issue:
        """Return the Issue with this id, with all its SubIssues.

        Raises:
            IssueNotFoundError: No Issue has this id.
        """
        ...

    def find_by_owner(self, node_id: NodeIdentifier) -> list[Issue]:
        """Return every Issue of this Node, oldest first."""
        ...

    def add(self, issue: Issue) -> None:
        """Store a new Issue and its SubIssues."""
        ...


class NodeDirectory(Protocol):
    """Reads the Node registry of Organizational Hierarchy."""

    def has_node(self, node_id: NodeIdentifier) -> bool:
        """Return whether a Node with this id is registered."""
        ...


class Clock(Protocol):
    """Tells the current time."""

    def now(self) -> datetime:
        """Return the current time, timezone-aware."""
        ...


class IdGenerator(Protocol):
    """Makes new unique ids."""

    def new_id(self) -> str:
        """Return an id no other Issue or SubIssue has."""
        ...


class EventPublisher(Protocol):
    """Hands domain events to whoever reacts to them."""

    def publish(self, events: Sequence[DomainEvent]) -> None:
        """Publish the events in order."""
        ...
