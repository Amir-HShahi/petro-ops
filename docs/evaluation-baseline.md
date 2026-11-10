# Evaluation baseline

This document records the evaluation metrics and targets agreed with the supervisor, as phase 1 of the spec requires. It fills in the values that spec §19 leaves as "agreed later".

The pass/fail checks for each component are in spec §19.1 and are not repeated here.

## How to read the tables

- **Target** is the value a feature must reach to count as done.
- **Baseline** is the first measured value. It stays empty until phase 2, when the first local models run against the golden set.
- **Status** is `proposed` until the supervisor agrees, then `agreed`. A changed target goes back to `proposed`.
- **Golden file** is the file in `fixtures/golden/` the metric is measured on.
- Judge scores use the rubric in spec §16, out of 20.

## Model and prompt metrics (spec §19.2)

| Metric | How it is measured | Golden file | Target | Baseline | Status |
|---|---|---|---|---|---|
| Retrieval relevance | Share of questions where an expected evidence passage is in the top K chunks (Recall@K) | `qa.jsonl` | Recall@5 ≥ 0.80 | | proposed |
| Answer faithfulness | Judge score for answers against their cited sources | `qa.jsonl` | Mean ≥ 18/20 | | proposed |
| Unanswerable questions | Share of questions with no answer in the knowledge where the answer says the knowledge is insufficient | `qa.jsonl` | ≥ 90% | | proposed |
| Summary quality | Judge score for TransferPackage summaries at the receiving Layer's detail level | `transfer_summary.jsonl` | Each important summary ≥ 18/20 (spec) | | proposed |
| Issue decomposition | Share of generated SubIssue sets accepted in human review as coherent and actionable | `issue_decomposition.jsonl` | ≥ 80% | | proposed |
| Executor matching | Share of Issues where an expected Executor is in the top 3, and share of match explanations that cite a profile, project or document | `executor_matching.jsonl` | Top 3 ≥ 80%; citations 100% | | proposed |
| RFP completeness | Share of mandatory RFP sections present in the generated draft | `fixtures/docs` RFP sample | 100% (spec) | | proposed |
| Proposal feedback | Share of main critiques that cite an RFP criterion or a Proposal section | `proposal_evaluation.jsonl` | 100% | | proposed |
| Prompt stability | Share of runs whose output passes the task's output schema, over 5 runs of the same structured input | Unit tests for prompt assembly and the output parser | 100% | | proposed |

## Thresholds left open in spec §19.1

| Threshold | Used by | Target | Status |
|---|---|---|---|
| Top-K | Embedding index, RAG context assembly | K = 5 | proposed |
| Exact duplicate | Duplicate detection | Same content hash | proposed |
| Near duplicate | Duplicate detection | Same normalized text hash (ADR 0010) | proposed |
| Chunk overlap | Overlap detection | ≥ 20% of a version's chunks have ≥ 40% of their 12-word shingles in another item of the same Node; 25% to 40% is ambiguous (ADR 0010) | proposed |
| Chunk size | Chunking | Target 400, hard limit 512 estimated tokens, 12% overlap within a section (ADR 0009) | proposed |
| Similar Issue | Issue comparison | Cosine similarity ≥ 0.80 | proposed |
| JudgeThreshold | LLM as judge | 18/20, unless manual review accepts the output (spec) | proposed |

Duplicate and overlap checks are lexical for now and were tuned on `fixtures/docs` (ADR 0010); embedding-based thresholds return with the vector index in phase 8. The other similarity thresholds depend on the embedding model. If phase 2 picks a model whose scores spread differently, they are re-tuned on the fixtures and go back to `proposed`.

## Sign-off

| Supervisor | Date | Notes |
|---|---|---|
| | | |
