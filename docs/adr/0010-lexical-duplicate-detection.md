# 0010. Lexical duplicate and overlap detection

Date: 2026-11-10
Status: Proposed

## Context
Spec §7.2 step 7 and §7.7 ask for exact duplicates, near duplicates and overlapping parts to be detected before indexing, and flagged rather than dropped silently. `docs/domain-model.md` describes a pure `DuplicateDetector` and leaves open what to do with a duplicate (open question 6) and who owns an item (open question 5). The vector index does not exist yet (phase 8). The checks must run offline and must not load a model in the ingestion workers.

## Decision
- **Flag, never reject.** A duplicate item is still created, or a version still published. The finding is stored as a `DuplicateFlag` (kind, existing item and version, score, `is_ambiguous`) and announced with `DuplicateDetected`.
- **Scope:** only items of the same owner Node are compared. A version is never compared with its own item, whose other versions are its history.
- **Exact duplicates** are found at submission and at `PublishKnowledgeVersion`: same SHA-256 of the file as any version of another item. The flag is written in the same transaction as the item.
- **Other kinds** are found in the chunking step (ADR 0009), once the text exists:
  - **Near duplicate:** same normalized text hash. The text includes the headings and is lower-cased, without punctuation, NFKC-normalized, with Arabic letters and Persian digits unified. It is a **metadata variant** when the `MetadataRecord` differs.
  - **Overlap:** each chunk is split into 12-word shingles. Its similarity to another item is the share of its shingles found in that item's active chunks (containment). When at least `OVERLAP_MIN_CHUNK_SHARE` of the chunks reach `OVERLAP_CHUNK_SIMILARITY`, the version gets an overlap flag. Its score is that share of chunks.
  - **Ambiguous:** when the share is only reached from `OVERLAP_AMBIGUOUS_FROM_SIMILARITY`, the overlap is flagged with `is_ambiguous`. No LLM is asked yet.
- Each existing item gets at most one flag, the strongest: exact, then near or metadata variant, then overlap.
- **Values,** tuned on `fixtures/docs` (estimated tokens, settings of ADR 0009): `DUPLICATE_SHINGLE_WORDS=12`, `OVERLAP_CHUNK_SIMILARITY=0.40`, `OVERLAP_AMBIGUOUS_FROM_SIMILARITY=0.25`, `OVERLAP_MIN_CHUNK_SHARE=0.20`.

Measured chunk similarities (containment, 12-word shingles):

| Case | Chunks of the candidate | Result |
|---|---|---|
| `cv_moradi_final.docx` vs `prof-01` | 1.0 each | exact |
| `inspection_sp12_riser_r3_2024.pdf` vs `ins-01` (DOCX) | 0.82, 0.83 | overlap, share 1.0. Not near: the PDF's document ID is `INS-01-PDF` |
| `shift_report_sp12_2026_09_27.docx` vs `ins-02-v1` | 0, 0, 0.54, 0 | overlap, share 0.25 |
| `ins-02-v2` vs `ins-02-v1`, if submitted as two items | 0.13, 0, 0.29, 0.69, 0.62, 0 | overlap, share 0.33 |
| `ins-01` vs `ins-02-v1` (same template, other year) | 0.14, 0, 0.19, 0, 0 | no flag |
| `ins-03`, `shift-03`, `proj-riser`, `bsee-519` vs `ins-02-v1` | at most 0.02 | no flag |

## Alternatives
- **Jaccard similarity between chunk pairs** (the first proposal). Chunk boundaries fall in different places in a PDF and a DOCX, so the format duplicate scored only 0.42 and 0.59. A copied paragraph inside a longer chunk scores low as well.
- **5- or 8-word shingles.** The two riser surveys share a template and table rows, and scored 0.48 to 0.59 (k=5) and 0.42 (k=8). That is as high as the real copy (0.54), so the two could not be told apart.
- **Embedding similarity**, as `docs/evaluation-baseline.md` first proposed. It needs the vector index of phase 8 and a model in the workers. It can be added later as another source of chunk similarities, since the detector only takes scores as data.
- **Rejecting or merging duplicates.** That is open question 6, so it is not decided here.

## Consequences
- The fixture cases are detected without any model, and their thresholds are checked in `tests/integration/knowledge/test_duplicate_cases_on_fixtures.py`.
- Lexical checks miss paraphrases and translations. Those wait for embeddings and the LLM check of the ambiguous band.
- Overlap compares every chunk with all active chunks of the Node, which costs time in proportion to the Node's text. That is fine at fixture scale. An inverted shingle index can replace it when a Node grows large.
- Two items of one Node chunked at the same moment may each miss the other, because neither sees the other's chunks yet. Reingesting either one finds the flag.
- With the manifest's owners, the shift report (`platform_sp12`) and the survey (`sp12_inspection_team`) are in different Nodes, so their overlap is not flagged. The same-Node rule waits for open question 5.
