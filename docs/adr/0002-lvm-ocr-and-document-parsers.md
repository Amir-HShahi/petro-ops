# 0002. LVM, OCR cross-check and document parsers

Date: 2026-11-03
Status: Proposed; DOCX, DOC and PDF-text parsers superseded by 0007

## Context
Phase 4 ingests DOC, DOCX and PDF files (spec §7.3, §21 phase 4). Scanned pages and layout-heavy pages need a local vision model (LVM) (spec §8.2, §19.1). ADR 0001 deferred the LVM until ingestion needed it.

The team develops on two machines: a MacBook Air M5 with 16 GB unified memory, and a laptop with an RTX 3060 Mobile (6 GB VRAM) and 15 GB RAM. The benchmark below ran on the M5 with Ollama 0.40, fully offline. The 3060 laptop is not measured yet.

The benchmark used its own English corpus of fictional "Platform Alpha" documents, not `fixtures/golden/`. Full results: [Phase 2 — Generator LLM & LVM Baseline](https://claude.ai/artifact/E2HZRGNxhpcqdCZmxibvAW).

Scanned tables in this project hold safety data, such as riser wall thickness readings (`scan-01`). A wrong reading there can raise a wrong Issue or hide a real one.

## Decision
- **LVM:** `gemma4:12b-it-qat`, the same model as the LLM, so it needs no extra memory. It runs only on pages with no text layer or pages flagged as visual. Pages are rendered at 150 DPI.
- **OCR cross-check:** `glm-ocr` reads every table on a scanned page as well. This is required, not optional. A table is flagged for human review when the two models disagree, or when its row count does not match its row labels.
- **DOCX:** `python-docx`.
- **DOC:** converted to DOCX with LibreOffice headless (`soffice`), then read with `python-docx`.
- **PDF:** `pdfplumber` for per-page text and for table cells, and `pypdfium2` for rendering pages for the LVM. Both are permissively licensed.
- **Text clean-up:** all extracted text is normalised with Unicode NFKC. A PDF ligature turned "retrofit" into "retroﬁt" in the benchmark.
- All models run through Ollama on the loopback address only, as in ADR 0001.

## Alternatives
Results on 30 hard scans of medium and hard quality:

| Metric | `glm-ocr` | `gemma4:12b-it-qat` |
|---|---|---|
| All tasks | 19/36 (53%) | 88/102 (86%) |
| Medium scans | 13/18 | 51/51 |
| Hard scans | 6/18 | 37/51 |
| Average fact recall (OCR) | 80% | 96% |
| Dense table rows | 4/6 | 3/6 |
| Visual Q&A (chart, ticked box, column) | not supported | 49/54 |
| Hallucination test | not supported | 12/12 |
| Time per page (OCR) | 12.8 s | 23.6 s |
| Image tokens per page | 2,788 | ~1,006 |

- **`glm-ocr` as the only LVM.** It is faster, but it drops chart values, page headers, memo dates and checkbox state. It is kept for tables, where its HTML output kept the row order right.
- **`glm-ocr` as an optional check.** Rejected. On a hard scan Gemma skipped one table row, so every later value moved up one row with no error shown. Gemma also misread digits on blurred scans (13.6 → 13.4, 8.6 → 6.6). With safety data, a silent error like this must be caught.
- **`qwen3-vl:8b`.** Downloaded but not benchmarked. It would add a second large model to memory.
- **PyMuPDF for PDF.** The benchmark used it, and its per-page text is good. It is licensed under AGPL-3.0, which would apply to the whole core when it is distributed as a wheel. `pypdfium2` is permissively licensed and can both extract text and render pages.
- **`pypdf` for PDF.** Pure Python and permissively licensed, but it cannot render pages for the LVM.
- **`pypdfium2` alone for PDF text.** It was the first choice here. It returns text but not table cells, so table rows lose their columns. `pdfplumber`, which builds on `pdfminer.six` and `pypdfium2`, finds tables and their position on the page.
- **macOS `textutil` for DOC and DOCX.** The benchmark used it, but it runs only on macOS. CI runs on Linux.

## Consequences
- Scanned pages are slow: about 24 s per page for Gemma, plus about 13 s for `glm-ocr` on pages with tables. Ingestion runs the LVM only where it is needed.
- Gemma and `glm-ocr` together do not fit next to the rest of a 16 GB machine. With both loaded, a three-page run pushed the M5 to 15.5 GB and into swap. So the LVM reads every page first and `glm-ocr` then reads the tables, and each model is unloaded from Ollama when its pass ends. On `scan-01` the system then peaked at 13.5 GB (9.3 GB of it other apps) with only one model loaded at a time, and nothing loaded afterwards.
- With the first page the model also loads, so the first scanned page of a run takes about a minute. Memory and speed on the 3060 laptop must be measured before ingestion is sized there.
- Since ADR 0007, Docling reads DOCX, DOC and text-layer PDFs; the rest of this point records the `pdfplumber` result it replaced. `pdfplumber` was not part of the benchmark. On the fixtures, its text and tables, together with `python-docx`, place all 113 golden quotes from DOCX files and text-layer PDFs on the right page or section; DOC quotes wait for LibreOffice (`tests/integration/knowledge/test_golden_evidence_extraction.py`). It writes glyphs it cannot map, such as bullets, as `(cid:N)`; the parser removes them.
- LibreOffice becomes a system dependency on both machines and in CI.
- The baseline in `docs/evaluation-baseline.md` stays empty until these models run on `fixtures/golden/`. `scan-01` and the real Cullen scan were not part of the benchmark.
- The `glm-ocr` tag is `latest`, which can move. The digest in `models/manifest.yaml` pins the tested weights.
- The parser libraries are added to `pyproject.toml` in the branch that implements extraction, not here.
