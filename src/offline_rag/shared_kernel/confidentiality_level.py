"""The visibility limit shared by Nodes and KnowledgeItems."""

from enum import StrEnum


class ConfidentialityLevel(StrEnum):
    """Visibility limit of knowledge, as used in the Node registry (spec §6.1, §7.5)."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
