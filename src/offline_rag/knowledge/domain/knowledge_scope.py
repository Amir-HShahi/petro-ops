"""Who may see a KnowledgeItem and what it may be used for."""

from dataclasses import dataclass
from enum import StrEnum


class ConfidentialityLevel(StrEnum):
    """Visibility limit of knowledge, as used in the Node registry (spec §6.1, §7.5)."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"


@dataclass(frozen=True, kw_only=True, slots=True)
class KnowledgeScope:
    """Confidentiality and usage scope of a KnowledgeItem (spec §5.3).

    The subject domain from spec §5.3 is kept in `MetadataRecord.domain`, where
    Issues share it, so it is not repeated here.

    Attributes:
        confidentiality: Who may see the item.
        usage_scope: Free text for now. Its allowed values wait for the
            "Confidentiality Per Layer" question in `docs/discovery-report.md`.
    """

    confidentiality: ConfidentialityLevel
    usage_scope: str | None = None
