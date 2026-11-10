"""Errors raised by the Knowledge Management domain."""

from offline_rag.shared_kernel.errors import DomainError, NotFoundError, UnexpectedError


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


class KnowledgeVersionNotFoundError(NotFoundError):
    """A KnowledgeItem has no version with the requested tag."""

    code = "KNOWLEDGE_VERSION_NOT_FOUND"

    def __init__(self, item_id: str, version_tag: str) -> None:
        """Create the error for the missing version."""
        super().__init__(
            f"KnowledgeItem '{item_id}' has no version '{version_tag}'.",
            details={"item_id": item_id, "version_tag": version_tag},
        )


class InvalidExtractedContentError(UnexpectedError):
    """A parser returned content that breaks the rules of `ExtractedContent`.

    Parsers are part of the core, so this means a bug in one of them.
    """

    code = "KNOWLEDGE_INVALID_EXTRACTED_CONTENT"

    def __init__(self, reason: str) -> None:
        """Create the error.

        Args:
            reason: Which rule the content breaks, in a short sentence.
        """
        super().__init__(
            f"Extracted content is invalid: {reason}",
            details={"reason": reason},
        )


class InvalidIngestionTransitionError(UnexpectedError):
    """A KnowledgeIngestion was asked to move to a status its current status does not allow.

    Workers skip finished runs, so this means a bug or a message for the wrong step.
    """

    code = "KNOWLEDGE_INGESTION_INVALID_TRANSITION"

    def __init__(self, ingestion_id: str, *, from_status: str, to_status: str) -> None:
        """Create the error for the refused move."""
        super().__init__(
            f"Ingestion '{ingestion_id}' cannot move from '{from_status}' to '{to_status}'.",
            details={
                "ingestion_id": ingestion_id,
                "from_status": from_status,
                "to_status": to_status,
            },
        )


class KnowledgeVersionChangeReasonMissingError(DomainError):
    """A new KnowledgeVersion was published without saying why the item changed (spec §7.6)."""

    code = "KNOWLEDGE_VERSION_CHANGE_REASON_MISSING"

    def __init__(self, item_id: str) -> None:
        """Create the error for the item that was to get a new version."""
        super().__init__(
            f"A new version of KnowledgeItem '{item_id}' needs a change reason. "
            "Say in a sentence what changed, then publish it again.",
            details={"item_id": item_id},
        )


class KnowledgeVersionUnchangedError(DomainError):
    """A file published as a new version is byte for byte the active version (spec §7.6)."""

    code = "KNOWLEDGE_VERSION_UNCHANGED"

    def __init__(self, item_id: str, active_version_tag: str) -> None:
        """Create the error naming the version the file repeats."""
        super().__init__(
            f"The file is the same as version '{active_version_tag}' of KnowledgeItem "
            f"'{item_id}', so there is nothing to publish.",
            details={"item_id": item_id, "active_version_tag": active_version_tag},
        )
