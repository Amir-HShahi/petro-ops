# 0012. Lexical similar-Issue check

Date: 2026-11-14
Status: Proposed

## Context
Spec §12.1 steps 3 and 4 ask that a new Issue be compared with the existing Issues of the same Node, and that likely duplicate or overlapping Issues be found. `docs/domain-model.md` describes a pure `SimilarIssueDetector` and planned to take its scores from the `Embedder`, but no embedding model is wired yet. The check runs in `issue raise` and must work offline. Issue texts are short: a title and one to three sentences. The 12-word shingles used for documents (ADR 0010) find almost nothing in texts this short.

## Decision
- **Flag, never reject.** The new Issue is always created. Each match is stored as a `SimilarIssueFlag` (the older Issue, its kind and its score) on the new Issue, saved in the same transaction, and announced with `SimilarIssueFound`.
- **Scope:** only Issues of the same owner Node are compared, and only the Issues themselves, not their SubIssues.
- **Words:** the title and description are NFKC-normalized and lower-cased, with Arabic letters and Persian digits unified as in ADR 0010. They are split into words, and a short English and Persian stop-word list is dropped. Hyphenated tags such as `R-3` or `P-4101A` stay one word.
- **Score:** the Dice similarity of the two word sets, `2·|A∩B| / (|A|+|B|)`.
- **Kinds:**
  - **Duplicate** from `SIMILAR_ISSUE_DUPLICATE_FROM`.
  - **Overlap** from `SIMILAR_ISSUE_OVERLAP_FROM`.
  - **Equipment rule:** a word with a letter and a digit counts as an equipment tag. When each text names a tag the other lacks (riser `R-2` versus `R-3`), the pair is at most an overlap.
- **Order:** duplicates first, then the highest score.
- **Values,** chosen on the golden Issues of `fixtures/golden/issue_decomposition.jsonl` and five hand-written variants: `SIMILAR_ISSUE_DUPLICATE_FROM=0.40`, `SIMILAR_ISSUE_OVERLAP_FROM=0.25`.

Measured scores (Dice, tags kept whole):

| New Issue | Existing Issue | Score | Result |
|---|---|---|---|
| R-3 corrosion in other words | `id-001` R-3 splash zone corrosion | 0.65 | duplicate |
| Short note on R-3 wall loss | `id-001` | 0.40 | duplicate |
| P-4101A keeps tripping | `id-002` repeated trips of P-4101A | 0.41 | duplicate |
| Coating failure on riser R-2 | Short note on R-3 wall loss | 0.57 | overlap: other riser |
| Coating failure on riser R-2 | `id-001` | 0.37 | overlap |
| `id-004` vibration on standby P-4101B | `id-002` | 0.31 | overlap |
| `id-005` R-3 coating breakdown | `id-001` | 0.28 | overlap |
| `id-003` safety barrier gap | `id-001` | 0.15 | no flag |
| Compressor K-101 vibration | any of the above | 0.11 or less | no flag |

## Alternatives
- **The 12-word shingles of ADR 0010.** A short Issue gives one shingle or a handful, so two descriptions of the same problem share none.
- **Jaccard similarity or the overlap coefficient.** On the same cases Jaccard squeezed duplicates and overlaps into 0.16 to 0.48, closer together than Dice. The overlap coefficient scored a short note as a 0.78 to 0.94 match with almost anything sharing its few words.
- **Splitting tags at the hyphen.** `R-2` and `R-3` became `r`, `2` and `r`, `3`, so the two risers looked the same and their coating Issues scored as duplicates.
- **Embedding similarity with `embeddinggemma`,** as `docs/domain-model.md` planned. It catches paraphrases, such as "wall loss" for "corrosion", but needs an `Embedder` port, an Ollama adapter and Ollama running for every `issue raise`. Chosen against for now. The detector already keeps the scoring in one place, so embeddings can replace or add to the word score later.
- **Rejecting likely duplicates.** A false match would block a real Issue. What to do with a duplicate is still open question 6.

## Consequences
- The check needs no model and adds one read of the Node's Issues to `issue raise`.
- Paraphrases are missed: an Issue written with other words for the same thing may get no flag.
- The duplicate threshold is reached exactly by the short R-3 note (0.40), so a slightly shorter note becomes an overlap. The values should be tuned again once there are more real Issues.
- A unit with a digit, such as `m2`, counts as an equipment tag. It only matters when each text has a tag the other lacks.
- Flags are stored only on the newer Issue. The older one does not point back.
