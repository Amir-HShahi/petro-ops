"""Metadata shared by Knowledge Management and Issue Management."""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True, slots=True)
class MetadataRecord:
    """Structured metadata of a KnowledgeItem or an Issue (spec §7.5). Every field is optional.

    The owning Node, the confidentiality level and the version ids are kept by the
    item itself, so they are not repeated here. Status, priority, target Layer and
    suggested detail level wait for their open questions in `docs/domain-model.md`.
    """

    domain: str | None = None
    subdomain: str | None = None
    project: str | None = None
    author: str | None = None
    document_type: str | None = None
    related_issue_ids: tuple[str, ...] = ()
    related_executor_ids: tuple[str, ...] = ()
    related_rfp_ids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    source_reliability: str | None = None
