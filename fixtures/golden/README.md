# Golden set

Hand-built expected outputs for the sample documents in `fixtures/docs/`. The metrics and targets they feed are in `docs/evaluation-baseline.md`. `tests/unit/test_golden_set.py` checks their structure.

## Files

| File | Rows | What it tests | Metric in `docs/evaluation-baseline.md` |
|---|---|---|---|
| `qa.jsonl` | 36 | Question answering over a Node's knowledge | Retrieval relevance (Recall@5), answer faithfulness, unanswerable questions |
| `executor_matching.jsonl` | 6 | Executors suggested for an Issue | Executor matching (top 3, citations) |
| `proposal_evaluation.jsonl` | 3 | Ranking and critique of each Proposal against RFP-01 | Proposal feedback |
| `issue_decomposition.jsonl` | 5 | SubIssues suggested for an Issue | Issue decomposition |
| `transfer_summary.jsonl` | 4 | TransferPackage summaries for a higher Layer | Summary quality |

Each file is JSON Lines: one UTF-8 JSON object per line.

## Common fields

- `id`: unique within the file, for example `qa-001`.
- `evidence`: list of `{"doc_id", "page_or_section", "quote"}`.
  - `doc_id` is an `id` from `fixtures/docs/manifest.csv`, never a chunk id. Evidence cites the canonical document (not a `duplicate_of` copy) and the latest version (not a `previous_version_id`).
  - `page_or_section` is `page N` for PDFs and the section heading for DOCX.
  - `quote` is an exact substring of the document text, 5 to 25 words. Whitespace may differ from the PDF text layer. Table rows are written as their cells joined with ` | `.
- `review_status`: `draft` or `reviewed`.
- `node_id`, `asked_from_node_id`, `source_node_id`: `node_id` values from `fixtures/registry/nodes.csv`.

## Fields per file

`qa.jsonl`

- `question_type`: `single_fact`, `table_lookup`, `multi_document`, `version_sensitive`, `scanned_pdf`, `unanswerable` or `layer_scope`.
- `node_id`: the Node whose knowledge answers the question. Except for `layer_scope`, the question is asked from this Node, and every evidence document belongs to it or a Node below it.
- `expected_answer`: the reference answer. For `unanswerable` rows it says the knowledge is insufficient, and `evidence` is empty.
- `version_sensitive` rows expect the newest version (`ins-02-v2`). The answer also names the superseded value so a judge can spot it.
- `layer_scope` rows add `asked_from_node_id` and `is_in_scope`. The scope of a Node is the Node and every Node below it in the registry. When `is_in_scope` is `false`, the evidence is the passage that must **not** be retrieved, and the expected answer says the knowledge is insufficient. Leave these rows out of Recall@K.

`executor_matching.jsonl`: `issue_title`, `issue_description`, `node_id` (where the Issue is raised) and `expected_executor_ids` (manifest ids of `personnel_profile` documents). Evidence cites the profiles a match explanation should point to.

`proposal_evaluation.jsonl`: `rfp_doc_id`, `proposal_doc_id`, `expected_rank` (1 is best), `mandatory_requirements_met` (`M1` to `M5` from RFP-01 section 8) and `expected_critiques` (`criterion` is an RFP-01 evaluation criterion or a mandatory requirement id).

`issue_decomposition.jsonl`: `issue_title`, `issue_description`, `node_id` and `expected_sub_issues` (short SubIssue titles). A generated set doesn't need the same wording, but it should cover the same ground.

`transfer_summary.jsonl`: `source_node_id`, `target_layer_index`, `detail_level` (the `received_detail_level` of the target Layer in `layers.csv`), `must_include` (key facts) and `must_not_include` (detail that is too fine for the Layer, or wrong).

## Review workflow

Every row starts as `draft`. A reviewer checks the answer and the evidence against the documents, fixes the row if needed, and sets `review_status` to `reviewed`. Only `reviewed` rows count for a baseline that is reported to the supervisor. A row that changes after review goes back to `draft`.

## How quotes were verified

Every quote was checked with a one-off script outside the repository. It extracted text with `python-docx` (paragraphs and table rows, grouped by heading) and `pypdf` (per page), normalised whitespace and Unicode (NFKC), and checked that each quote is in the given page or section and is 5 to 25 words long.

Two documents have no text layer:

- `scan-01`: quotes were checked against the source text in `scripts/build_fixtures.py`, which is rendered into the image, and by reading the rendered page.
- `pub-cullen-piper-alpha`: the quote was read from page 3 of the scan (printed page 277).

The unit test doesn't check quotes, because `python-docx` and `pypdf` are not project dependencies. Run the same kind of check again after changing a quote.
