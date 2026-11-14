"""Errors raised by the Issue Management domain."""

from offline_rag.shared_kernel.errors import DomainError


class IssueFieldEmptyError(DomainError):
    """An Issue or a SubIssue has an empty id, title or description (spec §12.1)."""

    code = "ISSUE_FIELD_EMPTY"

    def __init__(self, *, field: str) -> None:
        """Create the error for the empty field, such as `title`."""
        super().__init__(
            f"The {field.replace('_', ' ')} of an Issue or a SubIssue cannot be empty.",
            details={"field": field},
        )


class SubIssueIdTakenError(DomainError):
    """A SubIssue id is already used by the Issue or by another of its SubIssues."""

    code = "ISSUE_SUB_ISSUE_ID_TAKEN"

    def __init__(self, *, issue_id: str, sub_issue_id: str) -> None:
        """Create the error for the id that is already used."""
        super().__init__(
            f"Issue '{issue_id}' already has an Issue or a SubIssue with the id "
            f"'{sub_issue_id}'. Give the SubIssue another id.",
            details={"issue_id": issue_id, "sub_issue_id": sub_issue_id},
        )


class SubIssueParentNotFoundError(DomainError):
    """A SubIssue names a parent that is neither its Issue nor one of the Issue's SubIssues."""

    code = "ISSUE_SUB_ISSUE_PARENT_NOT_FOUND"

    def __init__(self, *, issue_id: str, sub_issue_id: str, parent_id: str) -> None:
        """Create the error for the SubIssue whose parent is not in the Issue."""
        super().__init__(
            f"SubIssue '{sub_issue_id}' names the parent '{parent_id}', which is not "
            f"Issue '{issue_id}' or one of its SubIssues.",
            details={"issue_id": issue_id, "sub_issue_id": sub_issue_id, "parent_id": parent_id},
        )


class SubIssueCycleError(DomainError):
    """The SubIssues of an Issue form a cycle, so they are not a tree (spec §12.2)."""

    code = "ISSUE_SUB_ISSUE_CYCLE"

    def __init__(self, *, issue_id: str, sub_issue_ids: list[str]) -> None:
        """Create the error for the SubIssues that form the cycle."""
        super().__init__(
            f"The SubIssues {', '.join(sub_issue_ids)} of Issue '{issue_id}' are each "
            "other's parents. SubIssues must form a tree under their Issue.",
            details={"issue_id": issue_id, "sub_issue_ids": sub_issue_ids},
        )


class InvalidSubIssuePositionError(DomainError):
    """The SubIssues under one parent are not numbered 1, 2, 3 and on (spec §12.2)."""

    code = "ISSUE_INVALID_SUB_ISSUE_POSITION"

    def __init__(self, *, issue_id: str, parent_id: str, positions: list[int]) -> None:
        """Create the error for the parent whose SubIssues are badly numbered."""
        super().__init__(
            f"The SubIssues under '{parent_id}' in Issue '{issue_id}' have the positions "
            f"{positions}. Their positions must run 1, 2, 3 and on without gaps.",
            details={"issue_id": issue_id, "parent_id": parent_id, "positions": positions},
        )


class InvalidSimilarIssueFlagError(DomainError):
    """A similar-Issue flag points at the Issue itself, or the same Issue is flagged twice."""

    code = "ISSUE_INVALID_SIMILAR_ISSUE_FLAG"

    def __init__(self, *, issue_id: str, similar_issue_id: str) -> None:
        """Create the error for the flag that cannot be kept."""
        super().__init__(
            f"Issue '{issue_id}' cannot be flagged as similar to '{similar_issue_id}': "
            "an Issue is never similar to itself, and each other Issue is flagged once.",
            details={"issue_id": issue_id, "similar_issue_id": similar_issue_id},
        )
