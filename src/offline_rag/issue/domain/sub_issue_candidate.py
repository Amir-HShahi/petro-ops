"""SubIssues the LLM suggests for an Issue, waiting for a person to accept them (spec §12.2).

The LLM only suggests; a person accepts the candidates worth keeping
(docs/application-services.md, `DecomposeIssue`). Each candidate cites the
knowledge it is based on (spec §12.5).
"""

from dataclasses import dataclass

from offline_rag.issue.domain.errors import IssueFieldEmptyError


@dataclass(frozen=True, kw_only=True, slots=True)
class Citation:
    """A passage of a KnowledgeItem that a candidate relies on (spec §12.5).

    Attributes:
        doc_id: The KnowledgeItem.
        page_or_section: Where in it the passage is, such as `p. 4` or a heading.
            Empty when the whole item is meant.
        quote: A short exact quote of the passage.
    """

    doc_id: str
    page_or_section: str
    quote: str

    def __post_init__(self) -> None:
        """Check that the citation names an item and quotes it.

        Raises:
            IssueFieldEmptyError: The item id or the quote is empty.
        """
        if not self.doc_id.strip():
            raise IssueFieldEmptyError(field="citation_doc_id")
        if not self.quote.strip():
            raise IssueFieldEmptyError(field="citation_quote")


@dataclass(frozen=True, kw_only=True, slots=True)
class SubIssueCandidate:
    """A SubIssue the LLM suggested, which a person may accept.

    Attributes:
        number: Its number within the Issue, from 1. A number is never reused, so
            it always names the same candidate.
        title: A short name of the suggested SubIssue.
        description: What the suggested SubIssue is about.
        citations: The knowledge it is based on. Empty when nothing it cited could
            be found in the knowledge it was given.
        accepted_sub_issue_id: The SubIssue it became, or None while it waits.
    """

    number: int
    title: str
    description: str
    citations: tuple[Citation, ...] = ()
    accepted_sub_issue_id: str | None = None

    def __post_init__(self) -> None:
        """Check that the candidate has a title and a description.

        Raises:
            IssueFieldEmptyError: The title or description is empty.
        """
        if not self.title.strip():
            raise IssueFieldEmptyError(field="candidate_title")
        if not self.description.strip():
            raise IssueFieldEmptyError(field="candidate_description")

    @property
    def is_accepted(self) -> bool:
        """Whether a person accepted it, so it became a SubIssue."""
        return self.accepted_sub_issue_id is not None
