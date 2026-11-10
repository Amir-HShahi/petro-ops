"""Use case: cut a KnowledgeVersion into chunks and check it for duplicates.

Spec §7.2 steps 5 and 7, §7.4, §7.7. The chunking worker runs it once the
content is extracted (ADR 0005, ADR 0009, ADR 0010).
"""

from collections import defaultdict
from dataclasses import dataclass

import structlog

from offline_rag.knowledge.application.commands import ChunkKnowledgeContent
from offline_rag.knowledge.application.duplicate_checks import (
    duplicate_detected_events,
    fingerprint_of,
)
from offline_rag.knowledge.application.ports import (
    Clock,
    DuplicateFlagRepository,
    EventPublisher,
    ExtractedContentRepository,
    KnowledgeChunkRepository,
    KnowledgeIngestionRepository,
    KnowledgeItemRepository,
    Tokenizer,
    VersionFingerprintRepository,
)
from offline_rag.knowledge.domain.chunking import chunk_content
from offline_rag.knowledge.domain.duplicate_detection import (
    DuplicateComparison,
    DuplicateDetector,
    DuplicateFlag,
    VersionFingerprint,
)
from offline_rag.knowledge.domain.extracted_content import ExtractedContent
from offline_rag.knowledge.domain.knowledge_chunk import KnowledgeChunk
from offline_rag.knowledge.domain.knowledge_ingestion import IngestionStatus, KnowledgeIngestion
from offline_rag.knowledge.domain.knowledge_item import KnowledgeItem
from offline_rag.knowledge.domain.text_fingerprint import (
    Shingles,
    chunk_containments,
    normalized_text_hash,
    reading_text,
    word_shingles,
)
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.shared_kernel.errors import InfrastructureError, ProjectError

log = structlog.get_logger()


@dataclass(frozen=True, kw_only=True)
class ChunkingSizes:
    """The chunk sizes of ADR 0009, from `Settings`.

    Attributes:
        target_tokens: The size a chunk grows to before a new one starts.
        max_tokens: The size no chunk may pass.
        overlap_share: Share of a chunk repeated at the start of the next one in
            the same section, from 0 to 0.5.
    """

    target_tokens: int
    max_tokens: int
    overlap_share: float


@dataclass(frozen=True)
class _ChunkingResult:
    content: ExtractedContent
    chunks: tuple[KnowledgeChunk, ...]
    flags: tuple[DuplicateFlag, ...]
    new_flags: tuple[DuplicateFlag, ...]


class ChunkKnowledgeContentHandler:
    """Chunks the stored content of a version, checks it for duplicates and completes the run.

    Every result replaces what an earlier run stored for the same version, so a
    message seen again is safe. A duplicate is only flagged; both items are kept.
    """

    def __init__(
        self,
        *,
        ingestion_repository: KnowledgeIngestionRepository,
        repository: KnowledgeItemRepository,
        extracted_content_repository: ExtractedContentRepository,
        chunk_repository: KnowledgeChunkRepository,
        fingerprint_repository: VersionFingerprintRepository,
        duplicate_flag_repository: DuplicateFlagRepository,
        tokenizer: Tokenizer,
        detector: DuplicateDetector,
        clock: Clock,
        event_publisher: EventPublisher,
        sizes: ChunkingSizes,
        words_per_shingle: int,
    ) -> None:
        """Create the handler.

        Args:
            ingestion_repository: Where KnowledgeIngestions are stored.
            repository: Where KnowledgeItems are stored.
            extracted_content_repository: Where the extracted blocks are kept.
            chunk_repository: Where the chunks go.
            fingerprint_repository: Finds other versions of the same Node by hash.
            duplicate_flag_repository: Where the flags go.
            tokenizer: Measures chunk sizes.
            detector: Decides which flags the version gets.
            clock: Stamps the ingestion and the events.
            event_publisher: Receives `DuplicateDetected`.
            sizes: How big chunks are.
            words_per_shingle: Words per shingle when chunk text is compared.
        """
        self._ingestion_repository = ingestion_repository
        self._repository = repository
        self._extracted_content_repository = extracted_content_repository
        self._chunk_repository = chunk_repository
        self._fingerprint_repository = fingerprint_repository
        self._duplicate_flag_repository = duplicate_flag_repository
        self._tokenizer = tokenizer
        self._detector = detector
        self._clock = clock
        self._event_publisher = event_publisher
        self._sizes = sizes
        self._words_per_shingle = words_per_shingle

    def chunk(self, command: ChunkKnowledgeContent) -> KnowledgeIngestion:
        """Chunk the version of an ingestion and return the ingestion in its new state.

        An error that a retry cannot fix, such as missing extracted content, ends
        the ingestion as FAILED instead of being raised.

        Raises:
            KnowledgeIngestionNotFoundError: The ingestion does not exist.
            InfrastructureError: A store or the database failed; the step can be retried.
        """
        ingestion = self._ingestion_repository.get_by_id(command.ingestion_id)
        if ingestion.status != IngestionStatus.CHUNKING:
            log.info(
                "knowledge_chunking_skipped",
                ingestion_id=ingestion.ingestion_id,
                status=ingestion.status.value,
            )
            return ingestion

        ingestion.start_chunking(self._clock.now())
        self._ingestion_repository.save(ingestion)
        try:
            result = self._chunk_and_check(ingestion)
        except InfrastructureError:
            raise
        except ProjectError as error:
            ingestion.fail(
                failure_code=error.code, failure_detail=str(error), now=self._clock.now()
            )
            self._ingestion_repository.save(ingestion)
            log.warning(
                "knowledge_chunking_failed",
                ingestion_id=ingestion.ingestion_id,
                item_id=ingestion.item_id,
                code=error.code,
            )
            return ingestion

        ingestion.complete(
            blocks_for_review=sum(block.needs_human_review for block in result.content.blocks),
            chunk_count=len(result.chunks),
            now=self._clock.now(),
        )
        self._ingestion_repository.save(ingestion)
        self._event_publisher.publish(
            duplicate_detected_events(result.new_flags, occurred_at=self._clock.now())
        )
        log.info(
            "knowledge_content_chunked",
            ingestion_id=ingestion.ingestion_id,
            item_id=ingestion.item_id,
            version_tag=ingestion.version_tag.value,
            chunk_count=len(result.chunks),
            max_chunk_tokens=max((chunk.token_count for chunk in result.chunks), default=0),
            duplicate_flags=[flag.kind.value for flag in result.flags],
        )
        return ingestion

    def _chunk_and_check(self, ingestion: KnowledgeIngestion) -> _ChunkingResult:
        item = self._repository.get_by_id(ingestion.item_id)
        version = item.get_version(ingestion.version_tag)
        content = self._extracted_content_repository.get(item.item_id, version.version_tag)
        chunks = chunk_content(
            content,
            item_id=item.item_id,
            version_tag=version.version_tag,
            metadata=version.metadata,
            count_tokens=self._tokenizer.count_tokens,
            target_tokens=self._sizes.target_tokens,
            max_tokens=self._sizes.max_tokens,
            overlap_share=self._sizes.overlap_share,
        )
        self._chunk_repository.replace(item.item_id, version.version_tag, chunks)

        text_hash = normalized_text_hash(reading_text(content))
        self._fingerprint_repository.save_text_hash(item.item_id, version.version_tag, text_hash)
        candidate = fingerprint_of(item, version, text_hash)
        flags = self._detector.detect(candidate, self._comparisons(item, candidate, chunks))

        stored_before = self._duplicate_flag_repository.list_by_version(
            item.item_id, version.version_tag
        )
        self._duplicate_flag_repository.replace(item.item_id, version.version_tag, flags)
        return _ChunkingResult(
            content=content,
            chunks=chunks,
            flags=flags,
            new_flags=tuple(flag for flag in flags if flag not in stored_before),
        )

    def _comparisons(
        self,
        item: KnowledgeItem,
        candidate: VersionFingerprint,
        chunks: tuple[KnowledgeChunk, ...],
    ) -> list[DuplicateComparison]:
        node_id = item.owner_node_id
        found = [
            *self._fingerprint_repository.find_by_content_hash(node_id, candidate.content_hash),
            *self._fingerprint_repository.list_active_by_owner(node_id),
        ]
        if candidate.normalized_text_hash is not None:
            found += self._fingerprint_repository.find_by_text_hash(
                node_id, candidate.normalized_text_hash
            )
        others = {
            (fingerprint.item_id, fingerprint.version_tag): fingerprint
            for fingerprint in found
            if fingerprint.item_id != item.item_id
        }

        # Only active chunks are compared: they are the ones retrieval can return.
        shingles_by_version: dict[tuple[str, VersionTag], set[str]] = defaultdict(set)
        for other_chunk in self._chunk_repository.list_active_by_owner(node_id):
            reference = other_chunk.source_reference
            if reference.item_id != item.item_id:
                shingles_by_version[(reference.item_id, reference.version_tag)] |= self._shingles(
                    other_chunk.text
                )
        candidate_shingles = [self._shingles(chunk.text) for chunk in chunks]

        return [
            DuplicateComparison(
                existing=fingerprint,
                chunk_similarities=chunk_containments(
                    candidate_shingles, frozenset(shingles_by_version[key])
                )
                if key in shingles_by_version
                else (),
            )
            for key, fingerprint in sorted(others.items(), key=_by_item_and_version)
        ]

    def _shingles(self, text: str) -> Shingles:
        return word_shingles(text, words_per_shingle=self._words_per_shingle)


def _by_item_and_version(
    entry: tuple[tuple[str, VersionTag], VersionFingerprint],
) -> tuple[str, str]:
    (item_id, version_tag), _ = entry
    return item_id, version_tag.value
