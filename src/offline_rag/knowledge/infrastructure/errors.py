"""Errors raised by the Knowledge Management adapters.

Messages never name file paths or library errors; those go to the logs.
"""

from offline_rag.shared_kernel.errors import DomainError, InfrastructureError


class KnowledgeStorageError(InfrastructureError):
    """The local knowledge database could not be read or written."""

    code = "KNOWLEDGE_STORAGE_FAILED"

    def __init__(self, operation: str) -> None:
        """Create the error.

        Args:
            operation: What was being done, such as `add` or `get_by_id`.
        """
        super().__init__(
            "The local knowledge database is not available. Try again, or check the data folder.",
            details={"operation": operation},
        )


class MessageBrokerUnavailableError(InfrastructureError):
    """The local message broker could not be reached or did not confirm a message (ADR 0005)."""

    code = "KNOWLEDGE_MESSAGE_BROKER_UNAVAILABLE"

    def __init__(self, operation: str) -> None:
        """Create the error.

        Args:
            operation: What was being done, such as `publish`.
        """
        super().__init__(
            "The local message broker is not available. Check that RabbitMQ is running, "
            "then try again.",
            details={"operation": operation},
        )


class SourceFileStorageError(InfrastructureError):
    """A file could not be written to or read from the local file store."""

    code = "KNOWLEDGE_SOURCE_FILE_STORAGE_FAILED"

    def __init__(self, file_name: str) -> None:
        """Create the error for the file that could not be stored or read."""
        super().__init__(
            f"The file '{file_name}' could not be stored or read. "
            "Check free disk space and the data folder.",
            details={"file_name": file_name},
        )


class NodeRegistryUnavailableError(InfrastructureError):
    """The Node registry file is missing or does not have the expected columns."""

    code = "KNOWLEDGE_NODE_REGISTRY_UNAVAILABLE"

    def __init__(self) -> None:
        """Create the error."""
        super().__init__(
            "The Node registry could not be read. Check NODE_REGISTRY_PATH and the file's columns.",
        )


class DocumentExtractionError(DomainError):
    """A file could not be read as the format its first bytes claim (spec §7.3)."""

    code = "KNOWLEDGE_EXTRACTION_FAILED"

    def __init__(self, document_format: str) -> None:
        """Create the error for the file that could not be parsed."""
        super().__init__(
            f"The file could not be read as {document_format.upper()}. It may be damaged, "
            "password protected or another file type. Open and save it again, then resubmit.",
            details={"document_format": document_format},
        )


class DocumentParserModelsUnavailableError(InfrastructureError):
    """Docling's layout or table-structure models are not in the local models folder (ADR 0007)."""

    code = "KNOWLEDGE_PARSER_MODELS_UNAVAILABLE"

    def __init__(self, missing_models: list[str]) -> None:
        """Create the error for the model folders that are missing."""
        super().__init__(
            "The document layout models are not installed. Download them into the folder "
            "set in DOCLING_MODELS_DIR, then run the ingestion again.",
            details={"missing_models": missing_models},
        )


class DocConverterUnavailableError(InfrastructureError):
    """DOC files need LibreOffice to be converted, and it is missing or failed (ADR 0007)."""

    code = "KNOWLEDGE_DOC_CONVERTER_UNAVAILABLE"

    def __init__(self) -> None:
        """Create the error."""
        super().__init__(
            "DOC files need LibreOffice, which is not installed or did not finish in time. "
            "Install LibreOffice or set LIBREOFFICE_PATH, then extract the item again.",
        )


class ModelUnavailableError(InfrastructureError):
    """The local model server cannot be reached, timed out or failed (ADR 0001)."""

    code = "KNOWLEDGE_MODEL_UNAVAILABLE"

    def __init__(self, model: str) -> None:
        """Create the error for the model that could not answer."""
        super().__init__(
            f"The local model '{model}' did not answer. Check that Ollama is running and "
            f"the model is pulled, then try again.",
            details={"model": model},
        )


class ModelOutputInvalidError(InfrastructureError):
    """A local model kept answering in a shape the output schema does not allow."""

    code = "KNOWLEDGE_MODEL_OUTPUT_INVALID"

    def __init__(self, model: str, attempts: int) -> None:
        """Create the error for the model and how often it was asked."""
        super().__init__(
            f"The local model '{model}' gave no valid answer in {attempts} attempts.",
            details={"model": model, "attempts": attempts},
        )


class ModelUrlNotLocalError(InfrastructureError):
    """The model server address is not on this machine, which the offline rule forbids."""

    code = "KNOWLEDGE_MODEL_URL_NOT_LOCAL"

    def __init__(self, host: str) -> None:
        """Create the error for the rejected host."""
        super().__init__(
            f"The model server '{host}' is not on this machine. Set OLLAMA_URL to a "
            "loopback address such as http://127.0.0.1:11434.",
            details={"host": host},
        )


class ModelRegistryUnavailableError(InfrastructureError):
    """The prompt registry or the model manifest is missing or incomplete."""

    code = "KNOWLEDGE_MODEL_REGISTRY_UNAVAILABLE"

    def __init__(self, task: str) -> None:
        """Create the error for the task whose prompt or model could not be loaded."""
        super().__init__(
            f"The prompt or model for task '{task}' could not be loaded. "
            "Check prompts/registry.yaml and models/manifest.yaml.",
            details={"task": task},
        )
