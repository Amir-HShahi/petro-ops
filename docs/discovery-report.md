# Domain discovery report

This is the phase 1 discovery report from spec §21. It summarizes what phase 1 found about the domain and where each result is kept. The spec in `docs/project-fa.md` is still the source of truth for scope and rules.

## Case study

The project is applied to an offshore oil and gas operator, described in `docs/scenario-offshore-fa.md`.

- Offshore platforms are remote and often cut off from networks, so a fully offline system fits naturally.
- The case fits a Persian Gulf University project.
- Safety work makes source references and the judge's quality gate matter. An unsupported claim about a failed safety barrier has serious consequences.
- Real inspection data is private, so most operational documents are synthetic. Public knowledge comes from incident reports, regulator safety alerts and open access papers.

## Layers and Nodes

The registry is in `fixtures/registry/`. `layers.csv` lists the Layers and `nodes.csv` lists the Nodes. Its README explains the columns, and `tests/unit/test_fixture_registry.py` checks the rules.

| Layer | Role | Detail level it receives | Nodes in the fixtures |
|---|---|---|---|
| 0 | National Oil Company | top executive | `national_oil_company` |
| 1 | Regional operators | managerial | `region_south_operator` |
| 2 | Offshore fields and platforms | technical summary | `platform_sp12`, `platform_sp14` |
| 3 | Inspection, maintenance, drilling and HSE teams | detailed technical | `sp12_inspection_team`, `sp12_maintenance_team`, `region_south_hse_team`, `region_south_well_operations_team` |
| 4 | Archive of standards, past incidents and personnel records (optional) | none | `region_south_archive` |

Rules found during discovery:

- A parent Node must be in a higher Layer, but it may skip Layers. For example, the regional HSE team in Layer 3 reports straight to the regional operator in Layer 1.
- A Node whose children are modelled tracks its internal structure. Leaf Nodes such as `platform_sp14` are treated as outside the system boundary (spec §6.1).

## Shared vocabulary

The shared vocabulary is on the "shared-vocabulary" page of the Lucid board PetroOps. It has the entities from spec §5.2 and the value objects from §5.3, with an example from the offshore case for each term where one exists. The same terms are used in code, tests and fixtures (`.claude/rules/naming.md`).

## Event storming

A Big Picture event storming was run on the "event-storming" page of the Lucid board. It has one lane per bounded context and time running left to right.

### Actors

| Actor | What they do |
|---|---|
| Governance Lead | Registers Nodes and defines Layer transfer rules |
| Field Reporter | Submits KnowledgeItems such as inspection and shift reports |
| Domain Engineer | Raises, decomposes and resolves Issues |
| Platform Manager | Sets Issue priority and approves TransferPackages |
| Procurement Officer | Publishes RFPs |
| Vendor | Submits Proposals |
| LLM Judge | Scores generated outputs |
| Scheduler | Triggers the Node processing cycle |

### External systems

- **Document Sources**: DOC, DOCX and PDF files.
- **Regulator Alerts**: for example BSEE and UK HSE.
- **Local LLM Runtime**: the offline models.
- **Offline Transfer Channel**: carries TransferPackages to the higher Layer without a network.

### Main flow

1. **Organizational Hierarchy.** Register Node, then Define Transfer Rule.
2. **Knowledge Management.** A KnowledgeItem is submitted and its metadata recorded. A duplicate may be detected, and a knowledge version is published. Readings and lessons learned are extracted from it.
3. **RAG Core.** Knowledge chunks are indexed, and grounded answers are generated with source references.
4. **Issue Management.** Events such as "Wall Loss Exceeded Threshold", "Repeated Failure Flagged" and "Barrier Degradation Reported" raise an Issue. The Issue is checked against similar Issues, prioritized, decomposed into SubIssues, and finally resolved. The resolution is stored back as knowledge.
5. **Issue-Knowledge-Executor.** Knowledge is linked to the Issue and Executors are proposed and assigned. A research gap leads to an RFP.
6. **RFP and Proposal.** An RFP is generated and published, and Proposals are received. Each Proposal is evaluated and gets a FeedbackReport, then one is awarded.
7. **Evaluation and Judging.** Every important output is judged. A failed judge gate leads to human review.
8. **Knowledge Transfer.** A completed Node cycle drafts a TransferPackage, which is judged and then accepted or rejected. A rejected package is regenerated, or the previous accepted version is reused. An approved package is delivered upward.

### Read models

Knowledge Inventory, Asset Integrity Register, Open Issues Board, IKE Graph View, Proposal Comparison, Judge Score Card and Platform Risk Summary.

## Bounded contexts

The context map is on the "domain-model-diagram" page of the Lucid board. It matches the ten contexts in spec §5.1. Each context has a code folder in `src/offline_rag/`.

| Context | Type | Code folder |
|---|---|---|
| Organizational Hierarchy | Supporting | `organization` |
| Knowledge Management | Core | `knowledge` |
| RAG Core | Generic | `rag` |
| Issue Management | Core | `issue` |
| Executor Management | Supporting | `executor` |
| Issue-Knowledge-Executor Model | Core | `executor`, `issue` and `knowledge` (not decided yet) |
| Knowledge Transfer | Core | `transfer` |
| Evaluation and Judging | Core | `evaluation` |
| RFP and Proposal | Supporting | `rfp` |
| Model and Prompt | Generic | `model_prompt` |

Main relationships on the map:

- Documents enter Knowledge Management through an anti-corruption layer.
- Organizational Hierarchy publishes `NodeIdentifier` and `LayerIndex` to the other contexts.
- Knowledge Management and Issue Management share `MetadataRecord`.
- Knowledge Transfer and Evaluation and Judging work as partners, scoring and retrying TransferPackages.
- Model and Prompt supplies models and prompts to RAG Core and Evaluation and Judging.

## Sample knowledge

`fixtures/docs/` has 40 sample documents, listed in `manifest.csv`:

- **22 synthetic documents.** Inspection reports, shift reports, personnel profiles, project reports, a root cause analysis, Node descriptions, an RFP and three Proposals.
- **7 test cases.** An exact duplicate, a format copy, a new version, a copied paragraph, two `.doc` files and a scanned PDF.
- **11 public excerpts.** BSEE and UK HSE safety alerts, the CSB Macondo report, the Cullen (Piper Alpha) report, and three CC-BY papers.

`fixtures/docs/README.md` lists the licences and the documents still to fetch by hand.

## Evaluation and testing

- The proposed metrics and thresholds are in `docs/evaluation-baseline.md`. They wait for the supervisor's agreement.
- The golden set in `fixtures/golden/` is what the metrics are measured on.
- The unit test approach follows spec §18 and the test levels in `.claude/CLAUDE.md`.

## Open questions

These are the hotspots from the event storming, plus the questions raised during phase 1.

| Question | Why it matters | Phase |
|---|---|---|
| Extraction Trust: how far can we trust text extracted from scans and layout-heavy PDFs? | Wrong readings lead to wrong Issues. | 4 |
| Cross-Node Duplicates: is the same KnowledgeItem held by two Nodes a duplicate? | Changes the duplicate and overlap rules. | 5 |
| Asset Entity Missing: the board talks about equipment such as risers and pumps, but the spec has no asset concept. | Needs a decision before a new domain term is added. | 3 |
| Alert Freshness: when is a regulator alert too old to match? | Affects matching alerts to equipment. | 8 |
| Progress Rule Conflict: what happens when SubIssue progress disagrees with the Issue status? | Spec §14.1 needs fixed, testable rules. | 7 |
| Who Checks Judge: how is the LLM judge itself checked? | Spec §16 relies on the judge for quality gates. | 10 |
| Confidentiality Per Layer: what may each Layer see? | Affects retrieval filters and TransferPackage content. | 6, 11 |
| Urgent Push Offline: how does an urgent package go up outside the normal cycle? | Spec §9 defines only cyclic processing. | 11 |
| The board uses names not in the spec: IKELink, IKEGraph, RetrievalRun, Citation, TransferItem and others. | They must be approved before they enter the vocabulary. | 3 |
| TransferDetailLevel is worded differently in spec §5.3 and §6.4. | Code needs one set of level names. | 3 |
