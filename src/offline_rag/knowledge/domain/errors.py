"""Errors raised by the Knowledge Management domain."""

from offline_rag.shared_kernel.errors import DomainError, UnexpectedError


class EmptySourceFileError(DomainError):
    """A submitted file has no content, so there is nothing to register."""

    code = "KNOWLEDGE_EMPTY_FILE"

    def __init__(self, file_name: str) -> None:
        """Create the error for the empty file."""
        super().__init__(
            f"The file '{file_name}' is empty. Submit a DOC, DOCX or PDF file with content.",
            details={"file_name": file_name},
        )


class UnsupportedDocumentFormatError(DomainError):
    """A submitted file is not DOC, DOCX or PDF (spec §7.3)."""

    code = "KNOWLEDGE_UNSUPPORTED_FORMAT"

    def __init__(self, file_name: str) -> None:
        """Create the error for the rejected file."""
        super().__init__(
            f"The file '{file_name}' is not a DOC, DOCX or PDF file. Convert it to one of these.",
            details={"file_name": file_name, "supported_formats": ["doc", "docx", "pdf"]},
        )


class InvalidKnowledgeVersionHistoryError(UnexpectedError):
    """A KnowledgeItem was built with a version history that breaks the rules of spec §7.6.

    Callers only build items through `KnowledgeItem.submit` or from stored data, so
    this means a bug or corrupted storage, not a bad request.
    """

    code = "KNOWLEDGE_INVALID_VERSION_HISTORY"

    def __init__(self, item_id: str, reason: str) -> None:
        """Create the error.

        Args:
            item_id: The KnowledgeItem whose history is broken.
            reason: Which rule the history breaks, in a short sentence.
        """
        super().__init__(
            f"KnowledgeItem '{item_id}' has an invalid version history: {reason}",
            details={"item_id": item_id, "reason": reason},
        )
