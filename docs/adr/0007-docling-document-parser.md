# 0007. Docling for DOCX and PDF text

Date: 2026-11-04
Status: Proposed

## Context
ADR 0002 chose `python-docx` and `pdfplumber` for documents with a text layer. The supervisor requires Docling, which extracts text, tables and heading structure for PDF and DOCX in one library. Docling downloads layout and table models on first use and pulls in PyTorch, but the project must run offline.

## Decision
- **DOCX and text-layer PDF:** Docling. Its output maps to `ContentBlock` (text or table, page number, heading path, source, review flag).
- **DOC:** converted to DOCX with LibreOffice headless (`soffice`), then read by Docling, which does not read `.doc`.
- **Models:** downloaded once into a local folder set in `Settings` and loaded from there at run time. A test run with the network off checks this.
- **Scanned pages:** unchanged from ADR 0002. Docling reads only the text layer; pages without one go to the vision lane (Gemma plus the `glm-ocr` table check). `pypdfium2` still renders pages at 150 DPI.
- Text is still normalised with Unicode NFKC.
- This supersedes the DOCX, DOC and PDF-text parts of ADR 0002.

## Alternatives
- **Keep `python-docx` and `pdfplumber`.** Lighter and already place all 113 golden quotes, but they do not meet the supervisor's requirement.
- **Docling's own OCR for scanned pages.** It would replace the benchmarked Gemma and `glm-ocr` lane without any evaluation on our scans.

## Consequences
- PyTorch makes the install much larger and slower.
- The golden-evidence test must still place all 113 quotes on the right page or heading with Docling.
- Model files live under `models/`, outside git, and must be copied to each machine.
- LibreOffice stays a system dependency on both machines and in CI.
