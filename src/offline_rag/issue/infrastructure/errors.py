"""Errors raised by the Issue Management adapters.

Messages never name file paths or library errors; those go to the logs.
"""

from offline_rag.shared_kernel.errors import InfrastructureError


class IssueStorageError(InfrastructureError):
    """The local database of Issues could not be read or written."""

    code = "ISSUE_STORAGE_FAILED"

    def __init__(self, operation: str) -> None:
        """Create the error.

        Args:
            operation: What was being done, such as `add` or `get_by_id`.
        """
        super().__init__(
            "The local Issue database is not available. Check that Postgres is running "
            "and the migrations have run, then try again.",
            details={"operation": operation},
        )


class NodeRegistryUnavailableError(InfrastructureError):
    """The registered Nodes of Organizational Hierarchy cannot be read."""

    code = "ISSUE_NODE_REGISTRY_UNAVAILABLE"

    def __init__(self) -> None:
        """Create the error."""
        super().__init__(
            "The registered Nodes could not be read. Check that Postgres is running "
            "and DATABASE_URL points to it.",
        )


class KnowledgeUnavailableError(InfrastructureError):
    """The KnowledgeItems of Knowledge Management cannot be read."""

    code = "ISSUE_KNOWLEDGE_UNAVAILABLE"

    def __init__(self) -> None:
        """Create the error."""
        super().__init__(
            "The knowledge could not be read. Check that Postgres is running and "
            "DATABASE_URL points to it.",
        )


class ModelUrlNotLocalError(InfrastructureError):
    """The model server address is not on this machine, which the offline rule forbids."""

    code = "ISSUE_MODEL_URL_NOT_LOCAL"

    def __init__(self, host: str) -> None:
        """Create the error for the rejected host."""
        super().__init__(
            f"The model server '{host}' is not on this machine. Set OLLAMA_URL to a "
            "loopback address such as http://127.0.0.1:11434.",
            details={"host": host},
        )


class ModelUnavailableError(InfrastructureError):
    """The local model server cannot be reached, timed out or failed (ADR 0001)."""

    code = "ISSUE_MODEL_UNAVAILABLE"

    def __init__(self, model: str) -> None:
        """Create the error for the model that could not answer."""
        super().__init__(
            f"The local model '{model}' did not answer. Check that Ollama is running and "
            "the model is pulled, then try again.",
            details={"model": model},
        )


class ModelRegistryUnavailableError(InfrastructureError):
    """The prompt registry or the model manifest is missing or incomplete."""

    code = "ISSUE_MODEL_REGISTRY_UNAVAILABLE"

    def __init__(self, task: str) -> None:
        """Create the error for the task whose prompt or model could not be loaded."""
        super().__init__(
            f"The prompt or model for task '{task}' could not be loaded. "
            "Check prompts/registry.yaml and models/manifest.yaml.",
            details={"task": task},
        )


class DecompositionAnswerInvalidError(InfrastructureError):
    """The LLM's answer to a decomposition was not the JSON the prompt asks for."""

    code = "ISSUE_DECOMPOSITION_ANSWER_INVALID"

    def __init__(self, *, model: str, attempts: int) -> None:
        """Create the error for the model that kept answering in the wrong shape."""
        super().__init__(
            f"The local model '{model}' did not answer with valid SubIssue suggestions "
            f"after {attempts} attempts. Try again, or name other KnowledgeItems.",
            details={"model": model, "attempts": attempts},
        )
