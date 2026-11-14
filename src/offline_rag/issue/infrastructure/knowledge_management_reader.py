"""KnowledgeItems read from the Knowledge Management context."""

from collections.abc import Sequence

from offline_rag.issue.application.errors import KnowledgeItemNotFoundError
from offline_rag.issue.application.ports import KnowledgePassage
from offline_rag.issue.infrastructure.errors import KnowledgeUnavailableError
from offline_rag.knowledge.application.errors import (
    KnowledgeItemNotFoundError as KnowledgeManagementItemNotFoundError,
)
from offline_rag.knowledge.application.knowledge_ingestion_queries import (
    KnowledgeIngestionQueries,
)
from offline_rag.knowledge.domain.source_reference import SourceReference
from offline_rag.shared_kernel.errors import InfrastructureError


class KnowledgeManagementReader:
    """Reads the active chunks of KnowledgeItems through Knowledge Management's queries.

    Issue Management only needs text and where it came from, so the chunks are turned
    into `KnowledgePassage`s and Knowledge Management's errors into Issue errors.
    """

    def __init__(self, queries: KnowledgeIngestionQueries) -> None:
        """Read the chunks through `queries`."""
        self._queries = queries

    def passages_of(self, item_ids: Sequence[str]) -> list[KnowledgePassage]:
        """Return the chunks of the active version of each item, item by item, in order.

        Raises:
            KnowledgeItemNotFoundError: An item does not exist.
            KnowledgeUnavailableError: The knowledge cannot be read.
        """
        passages: list[KnowledgePassage] = []
        for item_id in dict.fromkeys(item_ids):
            try:
                chunks = self._queries.get_chunks(item_id).chunks
            except KnowledgeManagementItemNotFoundError as error:
                raise KnowledgeItemNotFoundError(item_id) from error
            except InfrastructureError as error:
                raise KnowledgeUnavailableError from error
            passages.extend(
                KnowledgePassage(
                    item_id=item_id,
                    page_or_section=page_or_section(chunk.source_reference),
                    text=chunk.text,
                    token_count=chunk.token_count,
                )
                for chunk in chunks
            )
        return passages


def page_or_section(reference: SourceReference) -> str:
    """Return where a chunk is: its pages for a PDF, its heading path for DOC and DOCX."""
    if reference.page_start is not None:
        if reference.page_end in (None, reference.page_start):
            return f"p. {reference.page_start}"
        return f"pp. {reference.page_start}-{reference.page_end}"
    return " > ".join(reference.heading_path)
