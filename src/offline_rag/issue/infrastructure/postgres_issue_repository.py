"""Issue storage in the local Postgres database (spec §17, ADR 0004)."""

from dataclasses import asdict, fields
from typing import Any

from psycopg import Connection
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb

from offline_rag.issue.application.errors import IssueNotFoundError
from offline_rag.issue.domain.issue import Issue
from offline_rag.issue.domain.issue_status import IssueStatus
from offline_rag.issue.domain.similar_issue import SimilarIssueFlag, SimilarIssueKind
from offline_rag.issue.domain.sub_issue import SubIssue
from offline_rag.issue.infrastructure.postgres_database import PostgresDatabase
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

_INSERT_ISSUE = """
INSERT INTO issue (issue_id, owner_node_id, title, description, metadata, status, raised_at)
VALUES (%s, %s, %s, %s, %s, %s, %s)
"""

_INSERT_SUB_ISSUE = """
INSERT INTO sub_issue
    (issue_id, sub_issue_id, parent_id, position, title, description, metadata, status)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""

_INSERT_SIMILAR_ISSUE_FLAG = """
INSERT INTO similar_issue_flag (issue_id, similar_issue_id, kind, score) VALUES (%s, %s, %s, %s)
"""

# The order `SimilarIssueDetector` gives: duplicates first, then the highest score.
_SELECT_SIMILAR_ISSUE_FLAGS = """
SELECT * FROM similar_issue_flag WHERE issue_id = ANY(%s)
ORDER BY issue_id, kind <> 'duplicate', score DESC, similar_issue_id
"""

# JSON has no tuples, so these come back as lists and are turned back into tuples.
_TUPLE_METADATA_FIELDS = {
    field.name for field in fields(MetadataRecord) if field.type == tuple[str, ...]
}


class PostgresIssueRepository:
    """Stores each Issue as one row of `issue`, with its SubIssues in `sub_issue` and its
    similar-Issue flags in `similar_issue_flag`."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def get_by_id(self, issue_id: str) -> Issue:
        """Return the Issue with this id, with all its SubIssues.

        Raises:
            IssueNotFoundError: No Issue has this id.
            IssueStorageError: The database cannot be read.
        """
        with self._database.transaction("get_by_id") as connection:
            row = connection.execute(
                "SELECT * FROM issue WHERE issue_id = %s", (issue_id,)
            ).fetchone()
            if row is None:
                raise IssueNotFoundError(issue_id)
            sub_issues = _sub_issues_by_issue(connection, [issue_id])
            flags = _flags_by_issue(connection, [issue_id])
        return _issue_from_row(row, sub_issues.get(issue_id, []), flags.get(issue_id, []))

    def find_by_owner(self, node_id: NodeIdentifier) -> list[Issue]:
        """Return every Issue of this Node, oldest first.

        Raises:
            IssueStorageError: The database cannot be read.
        """
        with self._database.transaction("find_by_owner") as connection:
            rows = connection.execute(
                "SELECT * FROM issue WHERE owner_node_id = %s ORDER BY raised_at, issue_id",
                (node_id.value,),
            ).fetchall()
            issue_ids = [row["issue_id"] for row in rows]
            sub_issues = _sub_issues_by_issue(connection, issue_ids)
            flags = _flags_by_issue(connection, issue_ids)
        return [
            _issue_from_row(
                row, sub_issues.get(row["issue_id"], []), flags.get(row["issue_id"], [])
            )
            for row in rows
        ]

    def add(self, issue: Issue) -> None:
        """Store a new Issue, its SubIssues and its flags in one transaction.

        Raises:
            IssueStorageError: The database cannot be written, or the id is taken.
        """
        with self._database.transaction("add") as connection:
            connection.execute(
                _INSERT_ISSUE,
                (
                    issue.issue_id,
                    issue.owner_node_id.value,
                    issue.title,
                    issue.description,
                    Jsonb(asdict(issue.metadata)),
                    issue.status.value,
                    issue.raised_at,
                ),
            )
            for sub_issue in issue.sub_issues:
                connection.execute(
                    _INSERT_SUB_ISSUE,
                    (
                        issue.issue_id,
                        sub_issue.sub_issue_id,
                        sub_issue.parent_id,
                        sub_issue.position,
                        sub_issue.title,
                        sub_issue.description,
                        Jsonb(asdict(sub_issue.metadata)),
                        sub_issue.status.value,
                    ),
                )
            for flag in issue.similar_issue_flags:
                connection.execute(
                    _INSERT_SIMILAR_ISSUE_FLAG,
                    (issue.issue_id, flag.similar_issue_id, flag.kind.value, flag.score),
                )


def _sub_issues_by_issue(
    connection: Connection[DictRow], issue_ids: list[str]
) -> dict[str, list[SubIssue]]:
    if not issue_ids:
        return {}
    rows = connection.execute(
        "SELECT * FROM sub_issue WHERE issue_id = ANY(%s)", (issue_ids,)
    ).fetchall()
    sub_issues: dict[str, list[SubIssue]] = {}
    for row in rows:
        sub_issues.setdefault(row["issue_id"], []).append(
            SubIssue(
                sub_issue_id=row["sub_issue_id"],
                parent_id=row["parent_id"],
                position=row["position"],
                title=row["title"],
                description=row["description"],
                metadata=_metadata_from_json(row["metadata"]),
                status=IssueStatus(row["status"]),
            )
        )
    return sub_issues


def _flags_by_issue(
    connection: Connection[DictRow], issue_ids: list[str]
) -> dict[str, list[SimilarIssueFlag]]:
    if not issue_ids:
        return {}
    flags: dict[str, list[SimilarIssueFlag]] = {}
    for row in connection.execute(_SELECT_SIMILAR_ISSUE_FLAGS, (issue_ids,)).fetchall():
        flags.setdefault(row["issue_id"], []).append(
            SimilarIssueFlag(
                similar_issue_id=row["similar_issue_id"],
                kind=SimilarIssueKind(row["kind"]),
                score=row["score"],
            )
        )
    return flags


def _issue_from_row(
    row: dict[str, Any], sub_issues: list[SubIssue], flags: list[SimilarIssueFlag]
) -> Issue:
    return Issue(
        issue_id=row["issue_id"],
        owner_node_id=NodeIdentifier(row["owner_node_id"]),
        title=row["title"],
        description=row["description"],
        metadata=_metadata_from_json(row["metadata"]),
        status=IssueStatus(row["status"]),
        raised_at=row["raised_at"],
        sub_issues=sub_issues,
        similar_issue_flags=flags,
    )


def _metadata_from_json(stored_metadata: dict[str, Any]) -> MetadataRecord:
    metadata_fields: dict[str, Any] = {
        name: tuple(value) if name in _TUPLE_METADATA_FIELDS else value
        for name, value in stored_metadata.items()
    }
    return MetadataRecord(**metadata_fields)
