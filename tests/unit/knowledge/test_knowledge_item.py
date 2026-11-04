import dataclasses
from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from offline_rag.knowledge.domain.document_format import DocumentFormat
from offline_rag.knowledge.domain.errors import (
    InvalidKnowledgeVersionHistoryError,
    KnowledgeVersionNotFoundError,
)
from offline_rag.knowledge.domain.events import KnowledgeItemSubmitted, MetadataRecorded
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.domain.knowledge_version import (
    KnowledgeVersion,
    compute_content_hash,
)
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

SUBMITTED_AT = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
OWNER = NodeIdentifier("sp12_inspection_team")
SCOPE = KnowledgeScope(confidentiality=ConfidentialityLevel.INTERNAL)
METADATA = MetadataRecord(document_type="inspection_report", tags=("riser",))


def _submitted_item() -> KnowledgeItem:
    return KnowledgeItem.submit(
        item_id="ki-1",
        owner_node_id=OWNER,
        scope=SCOPE,
        metadata=METADATA,
        source_file_name="inspection_sp12_riser_r3_2024.docx",
        source_file_reference="file-1",
        document_format=DocumentFormat.DOCX,
        content_hash="abc123",
        submitted_at=SUBMITTED_AT,
    )


def _version(sequence_number: int, previous: str | None = None) -> KnowledgeVersion:
    return KnowledgeVersion(
        version_tag=VersionTag.for_sequence_number(sequence_number),
        sequence_number=sequence_number,
        source_file_name="report.pdf",
        source_file_reference=f"file-{sequence_number}",
        document_format=DocumentFormat.PDF,
        content_hash=f"hash-{sequence_number}",
        metadata=METADATA,
        created_at=SUBMITTED_AT,
        previous_version_tag=VersionTag(previous) if previous else None,
    )


def _rebuild(versions: list[KnowledgeVersion], active: str) -> KnowledgeItem:
    return KnowledgeItem(
        item_id="ki-1",
        owner_node_id=OWNER,
        scope=SCOPE,
        versions=versions,
        active_version_tag=VersionTag(active),
    )


def test_submitted_item_has_one_active_first_version_when_created():
    item = _submitted_item()

    assert len(item.versions) == 1
    assert item.active_version is item.versions[0]
    assert item.active_version.version_tag == VersionTag("v1")
    assert item.active_version.sequence_number == 1
    assert item.active_version.previous_version_tag is None
    assert item.active_version.change_reason is None


def test_submitted_item_keeps_what_was_submitted_when_created():
    item = _submitted_item()
    version = item.active_version

    assert item.item_id == "ki-1"
    assert item.owner_node_id == OWNER
    assert item.scope == SCOPE
    assert version.metadata == METADATA
    assert version.source_file_name == "inspection_sp12_riser_r3_2024.docx"
    assert version.source_file_reference == "file-1"
    assert version.document_format == DocumentFormat.DOCX
    assert version.content_hash == "abc123"
    assert version.created_at == SUBMITTED_AT


def test_submitted_item_records_submitted_and_metadata_events_when_created():
    events = _submitted_item().pull_events()

    assert events == (
        KnowledgeItemSubmitted(
            occurred_at=SUBMITTED_AT,
            item_id="ki-1",
            owner_node_id=OWNER,
            version_tag=VersionTag("v1"),
            document_format=DocumentFormat.DOCX,
            content_hash="abc123",
        ),
        MetadataRecorded(
            occurred_at=SUBMITTED_AT,
            item_id="ki-1",
            version_tag=VersionTag("v1"),
            metadata=METADATA,
        ),
    )


def test_events_are_returned_once_when_pulled_twice():
    item = _submitted_item()
    item.pull_events()

    assert item.pull_events() == ()


def test_version_cannot_be_changed_when_published():
    version = _submitted_item().active_version

    with pytest.raises(dataclasses.FrozenInstanceError):
        version.content_hash = "changed"  # type: ignore[misc]


def test_item_is_rebuilt_when_history_is_valid():
    item = _rebuild([_version(1), _version(2, previous="v1")], active="v2")

    assert item.active_version.sequence_number == 2
    assert item.pull_events() == ()


def test_items_are_equal_when_ids_match():
    rebuilt, submitted = _rebuild([_version(1)], active="v1"), _submitted_item()

    assert rebuilt == submitted
    assert hash(rebuilt) == hash(submitted)


@pytest.mark.parametrize(
    ("versions", "active", "reason"),
    [
        ([], "v1", "no versions"),
        ([_version(2)], "v2", "do not run 1, 2, 3"),
        ([_version(1), _version(3, previous="v1")], "v3", "do not run 1, 2, 3"),
        ([_version(1), _version(2)], "v1", "does not point to the version before it"),
        ([_version(1, previous="v0")], "v1", "does not point to the version before it"),
        ([_version(1)], "v2", "is not one of its versions"),
    ],
)
def test_item_is_rejected_when_history_breaks_a_rule(
    versions: list[KnowledgeVersion], active: str, reason: str
):
    with pytest.raises(InvalidKnowledgeVersionHistoryError, match=reason) as caught:
        _rebuild(versions, active)

    assert caught.value.code == "KNOWLEDGE_INVALID_VERSION_HISTORY"


def test_item_is_rejected_when_two_versions_share_a_tag():
    second = dataclasses.replace(_version(2, previous="v1"), version_tag=VersionTag("v1"))

    with pytest.raises(InvalidKnowledgeVersionHistoryError, match="share a tag"):
        _rebuild([_version(1), second], active="v1")


@given(content=st.binary())
def test_content_hash_is_the_same_when_content_is_the_same(content: bytes):
    assert compute_content_hash(content) == compute_content_hash(bytes(content))
    assert len(compute_content_hash(content)) == 64


@given(first=st.binary(), second=st.binary())
def test_content_hash_differs_when_content_differs(first: bytes, second: bytes):
    if first != second:
        assert compute_content_hash(first) != compute_content_hash(second)


def test_any_version_is_found_when_its_tag_is_asked_for():
    item = _rebuild([_version(1), _version(2, previous="v1")], active="v2")

    assert item.get_version(VersionTag("v1")).sequence_number == 1
    assert item.get_version(VersionTag("v2")) is item.active_version


def test_missing_version_is_reported_when_its_tag_is_unknown():
    with pytest.raises(KnowledgeVersionNotFoundError) as caught:
        _submitted_item().get_version(VersionTag("v7"))

    assert caught.value.code == "KNOWLEDGE_VERSION_NOT_FOUND"
    assert caught.value.details == {"item_id": "ki-1", "version_tag": "v7"}
