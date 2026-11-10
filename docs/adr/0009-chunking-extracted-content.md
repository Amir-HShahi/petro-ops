# 0009. Chunking extracted content

Date: 2026-11-10
Status: Proposed

## Context
Spec §7.2 step 5 and §7.4 ask for chunks that keep their source: item, version, page or section, heading path, order and inherited metadata. Retrieval (phase 8) embeds them with `embeddinggemma`, which reads at most 2048 tokens. The content comes from two lanes: Docling for DOC, DOCX and PDF with a text layer (ADR 0007), and the LVM for scanned pages (ADR 0002). Both end in the same `ExtractedContent`. DOCX headings are kept in `heading_path`; PDF headings stay in the page text. Everything must run offline on a 16 GB machine.

## Decision
- **Our own chunker in the domain.** `chunk_content` in `knowledge/domain/chunking.py` cuts `ExtractedContent` into `KnowledgeChunk`s. It is a pure function, so the same content and settings always give the same chunks and ids (`<item>/<version>/<order>`).
- **Rules:**
  - A change of heading path starts a new chunk.
  - Blocks of one section are packed in reading order until the next one would pass `CHUNK_TARGET_TOKENS`.
  - No chunk passes `CHUNK_MAX_TOKENS`. A longer paragraph is cut at line breaks, then sentences, then words, and only as a last resort inside a word.
  - A table that fits is kept whole. A longer one is cut between rows, and every part repeats the header row.
  - A chunk may start with the last sentences of the previous chunk, up to `CHUNK_OVERLAP_SHARE` of its size. This happens only within one section and never from a table.
  - A Hypothesis property test checks the hard limit.
- **Token count:** a `Tokenizer` port. The adapter `ApproximateTokenizer` counts one token per 4 characters, rounded up, and loads no model.
- **Source:** each chunk carries a `SourceReference` (item, version, heading path, first and last page), the first and last block it came from, and a copy of the version's `MetadataRecord`.
- **Lifecycle:** a chunk belongs to one version and never changes. Whether it is retrievable is derived, not stored: only chunks of the item's active version are retrievable. Publishing a new version (`PublishKnowledgeVersion`) supersedes the old chunks without touching them. Chunking a version again replaces its chunks.
- **Pipeline:** chunking is its own worker step and lane, `ingestion.chunking`. The ingestion runs QUEUED, EXTRACTING, READING_PAGES (only scanned pages), CHUNKING, then COMPLETED. The step is idempotent and retried like the others (ADR 0005). The reconciler resends lost CHUNKING messages.
- **Values,** tuned on `fixtures/docs`: `CHUNK_TARGET_TOKENS=400`, `CHUNK_MAX_TOKENS=512` (validated below 2048) and `CHUNK_OVERLAP_SHARE=0.12`. On the synthetic DOCX fixtures every section fits in one chunk; the PDFs, which have no heading path, give chunks of up to 428 estimated tokens.

## Alternatives
- **Docling's `HybridChunker`.** It works on a `DoclingDocument`, which the LVM lane does not produce, so scanned pages would need a second chunker. It also needs a Hugging Face tokenizer download.
- **A real tokenizer** (the embedding model's). This is more exact, but it ties chunking to a model that phase 8 may still change, and it loads weights in every chunking worker. The estimate is close for English. Persian may need more tokens per character, which is why the hard limit stays at a quarter of the model's context.
- **Fixed-size windows over the whole text.** These ignore headings and tables, so a chunk could mix two sections or cut a table row in half.
- **Chunking inside the text worker.** That would save a queue, but a chunking bug or retry would then re-run Docling. A separate lane keeps the steps small and visible on the pipeline page.

## Consequences
- Both extraction lanes give chunks in one form, with page or heading references an answer can cite.
- Token counts are estimates. Once the embedding model is fixed (phase 8), check the real counts on the Persian fixtures, and lower `CHUNK_MAX_TOKENS` if needed.
- PDF chunks have no heading path, because Docling cannot tell PDF heading levels reliably (ADR 0007). They cite pages instead.
- Changing a chunk setting changes chunks only for versions chunked afterwards. Reingest the versions that should follow it.
