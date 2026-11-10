"""The real LVM and OCR models on the scanned fixtures. Needs Ollama with both models pulled.

Each page takes about a minute on the M5 (ADR 0002), so the module reads two
pages in all and is marked slow. They skip when the local server or a model is missing, as in CI.
"""

import json
import re
import urllib.request
from pathlib import Path

import pytest

from offline_rag.bootstrap import build_knowledge
from offline_rag.knowledge.application.commands import (
    ExtractKnowledgeContent,
    ReadPagesWithLvm,
    SubmitKnowledgeItem,
)
from offline_rag.knowledge.domain.extracted_content import (
    TABLE_CELL_SEPARATOR,
    ContentSource,
    ExtractedContent,
    normalize_extracted_text,
)
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.infrastructure.postgres_extracted_content_repository import (
    PostgresExtractedContentRepository,
)
from offline_rag.settings import Settings
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

ROOT = Path(__file__).parents[3]
OLLAMA_URL = "http://127.0.0.1:11434"
REQUIRED_MODELS = {"gemma4:12b-it-qat", "glm-ocr:latest"}


def _pulled_models() -> set[str]:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3) as response:
            return {model["name"] for model in json.loads(response.read())["models"]}
    except OSError:
        return set()


pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.skipif(
        not _pulled_models() >= REQUIRED_MODELS, reason="needs Ollama with gemma4 and glm-ocr"
    ),
]


def _golden_quotes(doc_id: str) -> list[str]:
    quotes = []
    for line in (
        (ROOT / "fixtures" / "golden" / "qa.jsonl").read_text(encoding="utf-8").splitlines()
    ):
        quotes += [e["quote"] for e in json.loads(line)["evidence"] if e["doc_id"] == doc_id]
    return quotes


def _flatten(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_extracted_text(text)).casefold()


def _settings(data_dir: Path, ollama_url: str) -> Settings:
    return Settings(
        data_dir=data_dir,
        node_registry_path=ROOT / "fixtures" / "registry" / "nodes.csv",
        prompts_dir=ROOT / "prompts",
        model_manifest_path=ROOT / "models" / "manifest.yaml",
        ollama_url=ollama_url,
    )


def _read(data_dir: Path, relative_path: str, page_numbers: tuple[int, ...]) -> ExtractedContent:
    # Submitting only queues the ingestion, so extracting it by hand leaves it waiting
    # for page reading, and only the pages under test are read.
    knowledge = build_knowledge(_settings(data_dir, OLLAMA_URL))
    path = ROOT / "fixtures" / "docs" / relative_path
    receipt = knowledge.submit_handler.submit(
        SubmitKnowledgeItem(
            owner_node_id=NodeIdentifier("region_south_archive"),
            source_file_name=path.name,
            content=path.read_bytes(),
            scope=KnowledgeScope(confidentiality=ConfidentialityLevel.INTERNAL),
        )
    )
    knowledge.extract_handler.extract(ExtractKnowledgeContent(ingestion_id=receipt.ingestion_id))
    knowledge.read_pages_handler.read(
        ReadPagesWithLvm(ingestion_id=receipt.ingestion_id, page_numbers=page_numbers)
    )
    return PostgresExtractedContentRepository(knowledge.database).get(
        receipt.item_id, receipt.version_tag
    )


@pytest.fixture(scope="module")
def synthetic_scan(tmp_path_factory: pytest.TempPathFactory) -> ExtractedContent:
    # Read once and shared, since each reading takes about a minute.
    data_dir = tmp_path_factory.mktemp("scan_01") / "data"
    return _read(data_dir, "cases/scanned_sp12_riser_r3_baseline_2021.pdf", (1,))


def _lvm_texts(content: ExtractedContent, page_number: int) -> list[str]:
    texts = [
        _flatten(block.text)
        for block in content.blocks
        if block.source == ContentSource.LVM and block.page_number == page_number
    ]
    return texts + [text.replace(TABLE_CELL_SEPARATOR.casefold(), " ") for text in texts]


def test_golden_quotes_of_the_synthetic_scan_are_read_when_the_lvm_reads_it(
    synthetic_scan: ExtractedContent,
):
    texts = _lvm_texts(synthetic_scan, 1)
    for quote in _golden_quotes("scan-01"):
        assert any(_flatten(quote) in text for text in texts), quote


def test_readings_table_is_trusted_when_both_models_agree_on_the_synthetic_scan(
    synthetic_scan: ExtractedContent,
):
    readings = next(block for block in synthetic_scan.blocks if "Measured (mm)" in block.text)
    assert not readings.needs_human_review, readings.review_reason


def test_only_the_asked_page_is_read_when_pages_are_given(tmp_path: Path):
    content = _read(tmp_path / "data", "public/cullen_piper_alpha_volume2_ch17_excerpt.pdf", (3,))

    assert {block.page_number for block in content.blocks} == {3}
    texts = _lvm_texts(content, 3)
    for quote in _golden_quotes("pub-cullen-piper-alpha"):
        assert any(_flatten(quote) in text for text in texts), quote


def test_table_stays_between_its_paragraphs_when_the_synthetic_scan_is_read(
    synthetic_scan: ExtractedContent,
):
    texts = [block.text for block in synthetic_scan.blocks]
    readings = next(i for i, text in enumerate(texts) if "Measured (mm)" in text)
    coating = next(
        i for i, text in enumerate(texts) if text.startswith("Coating in good condition")
    )

    # In the source the readings table comes before the coating paragraph.
    assert readings < coating
