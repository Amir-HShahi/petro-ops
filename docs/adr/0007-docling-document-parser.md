# 0007. Docling for DOCX and PDF text

Date: 2026-11-04
Status: Proposed

## Context
ADR 0002 chose `python-docx` and `pdfplumber` for documents with a text layer. The supervisor requires Docling, which extracts text, tables and heading structure for PDF and DOCX in one library. Docling downloads layout and table models on first use and pulls in PyTorch, but the project must run offline.

## Decision
- **DOCX and text-layer PDF:** Docling. Its output maps to `ContentBlock` (text or table, page number, heading path, source, review flag).
- **DOC:** converted to DOCX with LibreOffice headless (`soffice`), then read by Docling, which does not read `.doc`.
- **Models:** only the layout model (`docling-layout-heron`) and the table-structure model (TableFormer, accurate mode), downloaded once with `docling-tools models download layout tableformer -o models/docling`. `DOCLING_MODELS_DIR` points at the folder, and Docling loads them only from there, with remote services off. If either is missing, reading a PDF fails with `KNOWLEDGE_PARSER_MODELS_UNAVAILABLE`, an infrastructure error, so the worker retries it. DOCX needs no models.
- **OCR is off.** Docling downloads no OCR models and reads no scanned pages.
- **Mapping to `ContentBlock`:** DOCX titles and `Heading N` paragraphs set the `heading_path` of the blocks below them and are not blocks themselves; paragraphs under one heading become one text block. A PDF block carries its page number, and PDF headings stay in the page text, since Docling gives every PDF heading level 1. Each table becomes one table block, and a merged cell is kept once. Docling also lists table cells as separate text items; those are skipped, so cell text is not repeated.
- **One converter per format**, so a DOCX submitted as a PDF is refused instead of being read as DOCX.
- **Scanned pages:** unchanged from ADR 0002. Docling reads only the text layer; pages without one go to the vision lane (Gemma plus the `glm-ocr` table check). `pypdfium2` still renders pages at 150 DPI.
- Text is still normalised with Unicode NFKC.
- This supersedes the DOCX, DOC and PDF-text parts of ADR 0002.

## Alternatives
- **Keep `python-docx` and `pdfplumber`.** Lighter and already place all 113 golden quotes, but they do not meet the supervisor's requirement.
- **Docling's own OCR for scanned pages.** It would replace the benchmarked Gemma and `glm-ocr` lane without any evaluation on our scans.

## Consequences
- PyTorch makes the install much larger and slower.
- Docling places all 113 golden quotes on the right page or heading: 99 from DOCX and DOC files, 14 from text-layer PDFs (`tests/integration/knowledge/test_golden_evidence_extraction.py`).
- The PDF tests pass with sockets blocked in the test, and in a Linux network namespace with no interface up. They are marked `slow` and skip when `models/docling` is missing, so CI must cache the models to run them.
- Reading the three fixture PDFs, the model load included, takes about 20 s on CPU (Intel i9-12900H, the laptop with 15 GB RAM).
- `pdfplumber` and `python-docx` are no longer project dependencies. `python-docx` stays installed as a dependency of Docling.
- Model files live under `models/`, outside git, and must be copied to each machine.
- LibreOffice stays a system dependency on both machines and in CI.
