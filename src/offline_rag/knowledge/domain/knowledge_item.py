"""The KnowledgeItem aggregate root."""

from collections.abc import Sequence
from datetime import datetime

from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.errors import (
    InvalidKnowledgeVersionHistoryError,
    KnowledgeVersionNotFoundError,
)
from offline_rag.knowledge.domain.events import KnowledgeItemSubmitted, MetadataRecorded
from offline_rag.knowledge.domain.knowledge_scope import KnowledgeScope
from offline_rag.knowledge.domain.knowledge_version import KnowledgeVersion
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.shared_kernel.domain_event import DomainEvent
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


class KnowledgeItem:
    """A controlled source of knowledge owned by one Node (spec §5.2, §7).

    Invariants (spec §7.6):
    - The item has at least one version, and old versions are never deleted.
    - Sequence numbers run 1, 2, 3 in order, without gaps.
    - Each `VersionTag` is unique within the item.
    - Each version after the first points to the version before it.
    - Exactly one version is active.
    """

    def __init__(
        self,
        *,
        item_id: str,
        owner_node_id: NodeIdentifier,
        scope: KnowledgeScope,
        versions: Sequence[KnowledgeVersion],
        active_version_tag: VersionTag,
    ) -> None:
        """Rebuild an item, for example from storage. Use `submit` for a new item.

        Raises:
            InvalidKnowledgeVersionHistoryError: The versions break an invariant.
        """
        _check_version_history(item_id, versions, active_version_tag)
        self._item_id = item_id
        self._owner_node_id = owner_node_id
        self._scope = scope
        self._versions = tuple(versions)
        self._active_version_tag = active_version_tag
        self._pending_events: list[DomainEvent] = []

    @classmethod
    def submit(
        cls,
        *,
        item_id: str,
        owner_node_id: NodeIdentifier,
        scope: KnowledgeScope,
        metadata: MetadataRecord,
        source_file_name: str,
        source_file_reference: str,
        document_format: DocumentFormat,
        content_hash: str,
        submitted_at: datetime,
    ) -> "KnowledgeItem":
        """Register a new item with its first, active version (spec §7.2 steps 1 and 2).

        The item records `KnowledgeItemSubmitted` and `MetadataRecorded`; take them
        with `pull_events` after saving it.
        """
        first_tag = VersionTag.for_sequence_number(1)
        first_version = KnowledgeVersion(
            version_tag=first_tag,
            sequence_number=1,
            source_file_name=source_file_name,
            source_file_reference=source_file_reference,
            document_format=document_format,
            content_hash=content_hash,
            metadata=metadata,
            created_at=submitted_at,
        )
        item = cls(
            item_id=item_id,
            owner_node_id=owner_node_id,
            scope=scope,
            versions=[first_version],
            active_version_tag=first_tag,
        )
        item._pending_events += [
            KnowledgeItemSubmitted(
                occurred_at=submitted_at,
                item_id=item_id,
                owner_node_id=owner_node_id,
                version_tag=first_tag,
                document_format=document_format,
                content_hash=content_hash,
            ),
            MetadataRecorded(
                occurred_at=submitted_at,
                item_id=item_id,
                version_tag=first_tag,
                metadata=metadata,
            ),
        ]
        return item

    @property
    def item_id(self) -> str:
        """Stable id of the item. It never changes across versions."""
        return self._item_id

    @property
    def owner_node_id(self) -> NodeIdentifier:
        """The Node that owns the item."""
        return self._owner_node_id

    @property
    def scope(self) -> KnowledgeScope:
        """Confidentiality and usage scope of the item."""
        return self._scope

    @property
    def versions(self) -> tuple[KnowledgeVersion, ...]:
        """All versions, oldest first."""
        return self._versions

    @property
    def active_version(self) -> KnowledgeVersion:
        """The version retrieval uses by default (spec §7.6)."""
        return next(v for v in self._versions if v.version_tag == self._active_version_tag)

    def get_version(self, version_tag: VersionTag) -> KnowledgeVersion:
        """Return the version with this tag. Old versions stay readable (spec §7.6).

        Raises:
            KnowledgeVersionNotFoundError: The item has no version with this tag.
        """
        for version in self._versions:
            if version.version_tag == version_tag:
                return version
        raise KnowledgeVersionNotFoundError(self._item_id, version_tag.value)

    def pull_events(self) -> tuple[DomainEvent, ...]:
        """Return the events recorded since the last call, and forget them."""
        events = tuple(self._pending_events)
        self._pending_events.clear()
        return events

    def __eq__(self, other: object) -> bool:
        return isinstance(other, KnowledgeItem) and other.item_id == self.item_id

    def __hash__(self) -> int:
        return hash(self.item_id)


def _check_version_history(
    item_id: str, versions: Sequence[KnowledgeVersion], active_version_tag: VersionTag
) -> None:
    if not versions:
        raise InvalidKnowledgeVersionHistoryError(item_id, "it has no versions.")

    sequence_numbers = [version.sequence_number for version in versions]
    if sequence_numbers != list(range(1, len(versions) + 1)):
        raise InvalidKnowledgeVersionHistoryError(
            item_id, f"sequence numbers {sequence_numbers} do not run 1, 2, 3 without gaps."
        )

    tags = [version.version_tag for version in versions]
    if len(set(tags)) != len(tags):
        raise InvalidKnowledgeVersionHistoryError(item_id, "two versions share a tag.")

    expected_previous_tags = [None, *tags[:-1]]
    actual_previous_tags = [version.previous_version_tag for version in versions]
    if actual_previous_tags != expected_previous_tags:
        raise InvalidKnowledgeVersionHistoryError(
            item_id, "a version does not point to the version before it."
        )

    if active_version_tag not in tags:
        raise InvalidKnowledgeVersionHistoryError(
            item_id, f"the active version {active_version_tag} is not one of its versions."
        )
