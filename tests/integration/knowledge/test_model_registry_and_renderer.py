import io
from pathlib import Path

import pytest
from PIL import Image

from offline_rag.knowledge.infrastructure.errors import (
    DocumentExtractionError,
    ModelRegistryUnavailableError,
)
from offline_rag.knowledge.infrastructure.model_registry import load_registered_prompt
from offline_rag.knowledge.infrastructure.pdfium_page_renderer import PdfiumPageRenderer

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[3]
SCANNED_PDF = ROOT / "fixtures" / "docs" / "cases" / "scanned_sp12_riser_r3_baseline_2021.pdf"
REGISTRIES = {
    "prompts_dir": ROOT / "prompts",
    "model_manifest_path": ROOT / "models" / "manifest.yaml",
}


def test_page_reading_runs_on_gemma_with_its_schema_when_loaded():
    prompt = load_registered_prompt(task="page_reading", **REGISTRIES)

    assert prompt.model == "gemma4:12b-it-qat"
    assert prompt.model_digest == "38044be4f923"
    assert prompt.version == 1
    assert prompt.output_schema is not None
    assert prompt.output_schema["required"] == ["items"]
    assert prompt.params["is_thinking_enabled"] is False
    assert not prompt.body.startswith("---")


def test_table_ocr_runs_on_glm_ocr_as_text_when_loaded():
    prompt = load_registered_prompt(task="table_ocr", **REGISTRIES)

    assert prompt.model == "glm-ocr:latest"
    assert prompt.body == "Table Recognition:"
    assert prompt.output_schema is None


def test_registry_error_is_raised_when_task_is_unknown():
    with pytest.raises(ModelRegistryUnavailableError) as caught:
        load_registered_prompt(task="no_such_task", **REGISTRIES)

    assert caught.value.code == "KNOWLEDGE_MODEL_REGISTRY_UNAVAILABLE"


def test_registry_error_is_raised_when_files_are_missing(tmp_path: Path):
    with pytest.raises(ModelRegistryUnavailableError):
        load_registered_prompt(
            task="page_reading", prompts_dir=tmp_path, model_manifest_path=tmp_path / "x.yaml"
        )


def test_page_is_rendered_as_png_at_the_set_resolution_when_drawn():
    image_png = PdfiumPageRenderer(dpi=150).render(SCANNED_PDF.read_bytes(), 1)

    image = Image.open(io.BytesIO(image_png))
    assert image.format == "PNG"
    # A4 is 8.27 x 11.69 inches, so about 1240 x 1754 pixels at 150 DPI.
    assert abs(image.width - 1240) < 15
    assert abs(image.height - 1754) < 15


@pytest.mark.parametrize(
    ("pdf", "page_number"),
    [(SCANNED_PDF.read_bytes(), 2), (SCANNED_PDF.read_bytes(), 0), (b"%PDF-1.7 broken", 1)],
    ids=["after-last-page", "page-zero", "broken-pdf"],
)
def test_render_error_is_raised_when_page_cannot_be_drawn(pdf: bytes, page_number: int):
    with pytest.raises(DocumentExtractionError):
        PdfiumPageRenderer(dpi=150).render(pdf, page_number)
