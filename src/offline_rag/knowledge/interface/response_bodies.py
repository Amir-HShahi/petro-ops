"""The JSON bodies the CLI prints and the API returns, so the two stay the same (ADR 0006)."""

from typing import Any

from offline_rag.knowledge.application.ingestion_queueing import IngestionReceipt
from offline_rag.knowledge.domain.extracted_content import (
    ContentBlockKind,
    ContentSource,
    ExtractedContent,
)
from offline_rag.knowledge.domain.knowledge_ingestion import KnowledgeIngestion
from offline_rag.knowledge.domain.version_tag import VersionTag


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
        "failure_code": ingestion.failure_code,
        "failure_detail": ingestion.failure_detail,
        "created_at": ingestion.created_at.isoformat(),
        "updated_at": ingestion.updated_at.isoformat(),
    }


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
