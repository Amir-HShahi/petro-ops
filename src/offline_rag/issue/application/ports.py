"""Ports of Issue Management: what its use cases need from the outside."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from offline_rag.issue.domain.issue import Issue
from offline_rag.issue.domain.sub_issue_candidate import SubIssueCandidate
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

    def save(self, issue: Issue) -> None:
        """Store the changes of an Issue that is already stored, its new SubIssues included.

        Raises:
            IssueNotFoundError: No Issue has this id.
        """
        ...


class NodeDirectory(Protocol):
    """Reads the Node registry of Organizational Hierarchy."""

    def has_node(self, node_id: NodeIdentifier) -> bool:
        """Return whether a Node with this id is registered."""
        ...


@dataclass(frozen=True, kw_only=True, slots=True)
class KnowledgePassage:
    """One chunk of a KnowledgeItem, as Issue Management reads it.

    Attributes:
        item_id: The KnowledgeItem, which citations name as `doc_id`.
        page_or_section: Where in the item the text is, such as `p. 4` or a heading
            path. Empty when the item has neither.
        text: The chunk text.
        token_count: Tokens in `text`, as Knowledge Management counted them.
    """

    item_id: str
    page_or_section: str
    text: str
    token_count: int


class KnowledgeReader(Protocol):
    """Reads KnowledgeItems of Knowledge Management."""

    def passages_of(self, item_ids: Sequence[str]) -> list[KnowledgePassage]:
        """Return the chunks of the active version of each item, item by item, in order.

        Raises:
            KnowledgeItemNotFoundError: An item does not exist.
        """
        ...


@dataclass(frozen=True, kw_only=True, slots=True)
class Decomposition:
    """What the LLM suggested for an Issue.

    Attributes:
        candidates: The suggested SubIssues in the LLM's order, numbered from 1.
        missing_information: What the LLM said the knowledge lacks, if anything.
    """

    candidates: tuple[SubIssueCandidate, ...]
    missing_information: str | None


class IssueDecomposer(Protocol):
    """Asks the local LLM to split an Issue into SubIssues (prompt `issue_decomposition`)."""

    def decompose(
        self, *, title: str, description: str, passages: Sequence[KnowledgePassage]
    ) -> Decomposition:
        """Return the SubIssues the LLM suggests, citing the passages they rely on.

        Raises:
            KnowledgeTooLargeError: The passages do not fit in the model's context.
        """
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
