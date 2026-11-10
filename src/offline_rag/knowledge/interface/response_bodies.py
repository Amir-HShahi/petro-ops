"""The JSON bodies the CLI prints and the API returns, so the two stay the same (ADR 0006)."""

from typing import Any

from offline_rag.knowledge.application.ingestion_queueing import IngestionReceipt
from offline_rag.knowledge.application.knowledge_ingestion_queries import (
    IngestionStatusView,
    VersionChunks,
)
from offline_rag.knowledge.application.ports import IngestionQueueDepth, KnowledgeIngestionSummary
from offline_rag.knowledge.domain.duplicate_detection import DuplicateFlag
from offline_rag.knowledge.domain.extracted_content import (
    ContentBlockKind,
    ContentSource,
    ExtractedContent,
)
from offline_rag.knowledge.domain.knowledge_ingestion import KnowledgeIngestion
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.shared_kernel.node_identifier import NodeIdentifier


def receipt_body(receipt: IngestionReceipt) -> dict[str, Any]:
    """Return the body for a version that was just queued for ingestion."""
    return {
        "item_id": receipt.item_id,
        "version_tag": receipt.version_tag.value,
        "ingestion_id": receipt.ingestion_id,
        "status": receipt.status.value,
    }


def ingestion_body(ingestion: KnowledgeIngestion) -> dict[str, Any]:
    """Return the body for the status of an ingestion."""
    return {
        "ingestion_id": ingestion.ingestion_id,
        "item_id": ingestion.item_id,
        "version_tag": ingestion.version_tag.value,
        "status": ingestion.status.value,
        "attempts": ingestion.attempts,
        "blocks_for_review": ingestion.blocks_for_review,
        "chunk_count": ingestion.chunk_count,
        "failure_code": ingestion.failure_code,
        "failure_detail": ingestion.failure_detail,
        "created_at": ingestion.created_at.isoformat(),
        "updated_at": ingestion.updated_at.isoformat(),
    }


def ingestion_status_body(view: IngestionStatusView) -> dict[str, Any]:
    """Return the body for the status of an ingestion with the flags of its version."""
    return {
        **ingestion_body(view.ingestion),
        "duplicate_flags": [duplicate_flag_body(flag) for flag in view.duplicate_flags],
    }


def duplicate_flag_body(flag: DuplicateFlag) -> dict[str, Any]:
    """Return the body for one duplicate flag."""
    return {
        "kind": flag.kind.value,
        "existing_item_id": flag.existing_item_id,
        "existing_version_tag": flag.existing_version_tag.value,
        "score": round(flag.score, 4),
        "is_ambiguous": flag.is_ambiguous,
    }


def chunks_body(item_id: str, found: VersionChunks, *, limit: int | None = None) -> dict[str, Any]:
    """Return the body for the chunks of a version.

    Args:
        item_id: The KnowledgeItem.
        found: The chunks and whether they are retrievable.
        limit: The most chunks to include, from the start. None includes all of them.
    """
    chunks = found.chunks if limit is None else found.chunks[:limit]
    return {
        "item_id": item_id,
        "version_tag": found.version_tag.value,
        "active_version_tag": found.active_version_tag.value,
        "is_retrievable": found.is_retrievable,
        "chunk_count": len(found.chunks),
        "chunks": [
            {
                "chunk_id": chunk.chunk_id,
                "order": chunk.order,
                "token_count": chunk.token_count,
                "heading_path": list(chunk.source_reference.heading_path),
                "page_start": chunk.source_reference.page_start,
                "page_end": chunk.source_reference.page_end,
                "first_block_order": chunk.first_block_order,
                "last_block_order": chunk.last_block_order,
                "text": chunk.text,
            }
            for chunk in chunks
        ],
    }


def recent_ingestions_body(summaries: list[KnowledgeIngestionSummary]) -> dict[str, Any]:
    """Return the body for the most recent ingestions, each with the file it reads."""
    return {
        "ingestions": [
            {
                **ingestion_body(summary.ingestion),
                "source_file_name": summary.source_file_name,
                "document_format": summary.document_format.value,
                "duplicate_flag_count": summary.duplicate_flag_count,
            }
            for summary in summaries
        ]
    }


def queue_depths_body(
    depths: list[IngestionQueueDepth], *, unpublished_outbox_messages: int
) -> dict[str, Any]:
    """Return the body for the broker queues and the messages still in the outbox."""
    return {
        "queues": [
            {
                "queue": depth.queue,
                "messages_ready": depth.messages_ready,
                "messages_unacked": depth.messages_unacked,
                "consumers": depth.consumers,
            }
            for depth in depths
        ],
        "unpublished_outbox_messages": unpublished_outbox_messages,
    }


def nodes_body(node_ids: list[NodeIdentifier]) -> dict[str, Any]:
    """Return the body for the registered Nodes."""
    return {"nodes": [{"node_id": node_id.value} for node_id in node_ids]}


def content_body(
    item_id: str,
    version_tag: VersionTag,
    extracted: ExtractedContent,
    *,
    min_page_text_chars: int,
    limit: int | None = None,
) -> dict[str, Any]:
    """Return the body for the content extracted from a version.

    Args:
        item_id: The KnowledgeItem.
        version_tag: The version the content was extracted from.
        extracted: The content.
        min_page_text_chars: The threshold below which a PDF page counts as having no text.
        limit: The most blocks to include, from the start. None includes all of them.
    """
    blocks = extracted.blocks if limit is None else extracted.blocks[:limit]
    return {
        "item_id": item_id,
        "version_tag": version_tag.value,
        "extraction": {
            "document_format": extracted.document_format.value,
            "page_count": extracted.page_count,
            "block_count": len(extracted.blocks),
            "table_count": sum(block.kind == ContentBlockKind.TABLE for block in extracted.blocks),
            "lvm_block_count": sum(block.source == ContentSource.LVM for block in extracted.blocks),
            "blocks_for_review": sum(block.needs_human_review for block in extracted.blocks),
            "pages_without_text": list(
                extracted.pages_without_text(min_page_text_chars=min_page_text_chars)
            ),
        },
        "blocks": [
            {
                "order": block.order,
                "kind": block.kind.value,
                "page_number": block.page_number,
                "heading_path": list(block.heading_path),
                "source": block.source.value,
                "needs_human_review": block.needs_human_review,
                "review_reason": block.review_reason,
                "text": block.text,
            }
            for block in blocks
        ],
    }
