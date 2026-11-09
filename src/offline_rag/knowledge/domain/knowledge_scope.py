"""Who may see a KnowledgeItem and what it may be used for."""

from dataclasses import dataclass

from offline_rag.shared_kernel.confidentiality_level import ConfidentialityLevel

# Organizational Hierarchy uses the same levels for Nodes, so the enum lives in the
# shared kernel. It is re-exported here so existing imports keep working.
__all__ = ["ConfidentialityLevel", "KnowledgeScope"]


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
