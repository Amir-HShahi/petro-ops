"""Use case: ask the LLM to suggest SubIssues for an Issue (spec §12.2, §12.5)."""

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

import structlog

from offline_rag.issue.application.commands import DecomposeIssue
from offline_rag.issue.application.errors import KnowledgeRequiredError
from offline_rag.issue.application.ports import (
    IssueDecomposer,
    IssueRepository,
    KnowledgePassage,
    KnowledgeReader,
)
from offline_rag.issue.domain.issue import Issue
from offline_rag.issue.domain.sub_issue_candidate import Citation, SubIssueCandidate

log = structlog.get_logger()

_SPACES = re.compile(r"\s+")


@dataclass(frozen=True, kw_only=True)
class DecompositionResult:
    """The Issue with its new candidates, and what the LLM said was missing.

    Attributes:
        issue: The Issue, with the new candidates waiting to be accepted.
        candidates: The new candidates with their numbers.
        missing_information: What the LLM said the knowledge lacks, if anything.
        dropped_citation_count: Citations left out because their quote is not in the
            KnowledgeItem they name.
    """

    issue: Issue
    candidates: tuple[SubIssueCandidate, ...]
    missing_information: str | None
    dropped_citation_count: int


class DecomposeIssueHandler:
    """Stores the SubIssues the LLM suggests as candidates a person may accept.

    The LLM reads only the KnowledgeItems it is given. A citation whose quote is not
    in the item it names is dropped, since a SubIssue must be grounded in sources
    (spec §12.5).
    """

    def __init__(
        self,
        *,
        issue_repository: IssueRepository,
        knowledge_reader: KnowledgeReader,
        decomposer: IssueDecomposer,
    ) -> None:
        """Create the handler with the ports it needs."""
        self._issue_repository = issue_repository
        self._knowledge_reader = knowledge_reader
        self._decomposer = decomposer

    def decompose(self, command: DecomposeIssue) -> DecompositionResult:
        """Ask the LLM for candidates, store them on the Issue and return them.

        The new candidates replace those still waiting from an earlier run.

        Raises:
            KnowledgeRequiredError: No KnowledgeItem was given.
            IssueNotFoundError: The Issue does not exist.
            KnowledgeItemNotFoundError: A KnowledgeItem does not exist.
            KnowledgeTooLargeError: The knowledge does not fit in the model's context.
        """
        if not command.knowledge_item_ids:
            raise KnowledgeRequiredError(command.issue_id)
        issue = self._issue_repository.get_by_id(command.issue_id)
        passages = self._knowledge_reader.passages_of(command.knowledge_item_ids)
        decomposition = self._decomposer.decompose(
            title=issue.title, description=issue.description, passages=passages
        )
        checked = [
            _keep_found_citations(candidate, passages) for candidate in decomposition.candidates
        ]
        dropped = sum(
            len(original.citations) - len(kept.citations)
            for original, kept in zip(decomposition.candidates, checked, strict=True)
        )
        candidates = issue.propose_sub_issue_candidates(checked)
        self._issue_repository.save(issue)
        log.info(
            "issue_decomposition_suggested",
            issue_id=issue.issue_id,
            node_id=issue.owner_node_id.value,
            knowledge_items=len(command.knowledge_item_ids),
            passages=len(passages),
            candidates=len(candidates),
            dropped_citations=dropped,
        )
        return DecompositionResult(
            issue=issue,
            candidates=candidates,
            missing_information=decomposition.missing_information,
            dropped_citation_count=dropped,
        )


def _keep_found_citations(
    candidate: SubIssueCandidate, passages: Sequence[KnowledgePassage]
) -> SubIssueCandidate:
    return replace(
        candidate,
        citations=tuple(
            citation for citation in candidate.citations if _is_quoted(citation, passages)
        ),
    )


def _is_quoted(citation: Citation, passages: Sequence[KnowledgePassage]) -> bool:
    quote = _comparable(citation.quote)
    return any(
        passage.item_id == citation.doc_id and quote in _comparable(passage.text)
        for passage in passages
    )


def _comparable(text: str) -> str:
    # The LLM may change line breaks or letter case when it quotes.
    return _SPACES.sub(" ", text).strip().casefold()
