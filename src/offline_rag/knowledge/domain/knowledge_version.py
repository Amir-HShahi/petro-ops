"""One version of a KnowledgeItem and the hash that identifies its file."""

import hashlib
from dataclasses import dataclass
from datetime import datetime

from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.shared_kernel.metadata_record import MetadataRecord


@dataclass(frozen=True, kw_only=True, slots=True)
class KnowledgeVersion:
    """One version of a KnowledgeItem (spec §7.6). A published version never changes.

    Whether a version is active is kept by its KnowledgeItem, so that exactly one
    version can be active at a time.

    Attributes:
        version_tag: Immutable id, unique within the item.
        sequence_number: 1 for the first version, then one higher for each update.
        source_file_name: The name the file was submitted with, for source references.
        source_file_reference: Where `SourceFileStore` keeps the original file.
        document_format: Format detected from the file content.
        content_hash: SHA-256 of the file, used for exact duplicate checks (spec §7.7).
        metadata: The metadata recorded with this version.
        created_at: When the version was created.
        change_reason: Why the item was updated. None for the first version.
        previous_version_tag: The version this one replaces. None for the first version.
        diff_summary: Optional short summary of what changed.
    """

    version_tag: VersionTag
    sequence_number: int
    source_file_name: str
    source_file_reference: str
    document_format: DocumentFormat
    content_hash: str
    metadata: MetadataRecord
    created_at: datetime
    change_reason: str | None = None
    previous_version_tag: VersionTag | None = None
    diff_summary: str | None = None


def compute_content_hash(content: bytes) -> str:
    """Return the SHA-256 hex digest of a file. Byte-identical files get the same hash."""
    return hashlib.sha256(content).hexdigest()
