"""The status of an Issue or a SubIssue (spec §14.1)."""

from enum import StrEnum


class IssueStatus(StrEnum):
    """Where an Issue or a SubIssue stands in its life (spec §14.1).

    The spec lists the statuses but not which may follow which, so every new Issue
    starts as `NEW` and the rules for moving between them come later
    (docs/domain-model.md, open question 6).
    """

    NEW = "new"
    ANALYZING = "analyzing"
    KNOWLEDGE_IDENTIFIED = "knowledge_identified"
    EXECUTOR_IDENTIFIED = "executor_identified"
    SOLUTION_PROPOSED = "solution_proposed"
    IN_EXECUTION = "in_execution"
    AWAITING_DECISION = "awaiting_decision"
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    ARCHIVED = "archived"
