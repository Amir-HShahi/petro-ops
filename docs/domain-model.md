# Domain model

This document is the phase 3 domain model. It lists, for each bounded context, the aggregate roots, entities, value objects, invariants and domain events.

Sources:

- Spec §5 to §17 in `docs/project-fa.md` (source of truth).
- The "domain-model-diagram", "event-storming" and "aggregates-detail" pages of the Lucid board PetroOps.
- `docs/discovery-report.md` for actors, the main flow and the context table. This file does not repeat them.
- `fixtures/registry/` for Layer and Node rules, `docs/evaluation-baseline.md` for metrics, `docs/errors.md` for the error contract.
- `models/manifest.yaml` and `prompts/registry.yaml` for models and prompts.

## How to read this document

- **AR** is an aggregate root, **E** an entity inside an aggregate, **VO** a value object.
- Names without a mark come from spec §5.2 (entities) or §5.3 (value objects). They are approved for code.
- A name marked **(proposed)** appears only on the Lucid board. It is not approved and must not be used in code until the user approves it (`.claude/rules/naming.md`).
- A rule marked **(interpretation)** is not stated in the spec as written. It is our reading and needs the supervisor's agreement.
- Event names are the board names without spaces, for example "Node Registered" becomes `NodeRegistered`.
- Each aggregate is one consistency boundary. Aggregates refer to each other by id only.

## Overview

| Context | Type | Code folder | Aggregate roots |
|---|---|---|---|
| Organizational Hierarchy | Supporting | `organization` | `Node`, `Layer` |
| Knowledge Management | Core | `knowledge` | `KnowledgeItem` |
| RAG Core | Generic | `rag` | `RetrievalRun` (proposed) |
| Issue Management | Core | `issue` | `Issue` |
| Executor Management | Supporting | `executor` | `Executor` |
| Issue-Knowledge-Executor Model | Core | not decided, see open question 1 | `IKEGraph` (proposed) |
| Knowledge Transfer | Core | `transfer` | `TransferPackage` |
| Evaluation and Judging | Core | `evaluation` | `JudgeScore` |
| RFP and Proposal | Supporting | `rfp` | `RFP`, `Proposal` |
| Model and Prompt | Generic | `model_prompt` | `PromptTemplate` (proposed), `ModelConfig` (proposed) |

## 1. Organizational Hierarchy

Spec §6. Registry data is in `fixtures/registry/`.

### Aggregate roots

**`Node`**

- Key attributes: `NodeIdentifier`, name, `LayerIndex`, parent `NodeIdentifier`, activity area, reporting rule, confidentiality limit, `is_internal_structure_tracked`.
- Invariants:
  - The `NodeIdentifier` is stable and never changes (§5.3).
  - A Node belongs to exactly one Layer.
  - A parent Node is always in a higher Layer (lower index). It may skip Layers (registry README).
  - Only the Layer 0 Node has no parent.
  - The parent chain has no cycle. This follows from the Layer rule.
  - The children of a Node are modelled only when `is_internal_structure_tracked` is true. Otherwise the Node is outside the system boundary (§6.1).

**`Layer`**

- Key attributes: `LayerIndex`, name, role, `TransferDetailLevel` it receives, transfer rules.
- Invariants:
  - `LayerIndex` is unique and from 0 to 4 (§6.2).
  - Layer 4 is optional and receives no `TransferPackage`. It only provides knowledge (registry README).
  - The transfer rules of a Layer are required and excluded topics, detail level, output format, minimum judge score, maximum package length and source reference level (§10.1).
  - The minimum judge score of a Layer must be a valid `JudgeThreshold`.

### Entities and value objects

| Name | Kind | Rule it enforces |
|---|---|---|
| `ReportingRule` (proposed) | E of `Node` | Says how often the Node reports to its parent. The registry stores it as a plain cadence such as `weekly`. |
| `NodeIdentifier` | VO | Stable id of a Node. Published to all other contexts. |
| `LayerIndex` | VO | Whole number from 0 to 4. Lower means higher in the hierarchy. Published to all other contexts. |

### Domain events

`NodeRegistered`, `LayerTransferRuleDefined`.

## 2. Knowledge Management

Spec §7 and §11.1. The core of the system.

### Aggregate root

**`KnowledgeItem`**

- Key attributes: item id, owner `NodeIdentifier`, `KnowledgeScope`, `MetadataRecord`, active `VersionTag`, its `KnowledgeVersion`s.
- Invariants:
  - Every update creates a new `KnowledgeVersion`. Old versions are never deleted (§7.6).
  - Exactly one version is active at a time. Retrieval uses the active version by default (§7.6).
  - A `VersionTag` is immutable and unique within the item.
  - An item has one owner Node (open question 5).
  - Duplicates and overlaps are detected before indexing and flagged, never dropped silently (§7.2, §7.7). The action on a duplicate is not defined in the spec (open question 6).
  - A generated RFP, a resolved Issue answer and a RAG answer worth keeping are stored as a `KnowledgeItem` (§8.1, §15.1).

### Entities and value objects

| Name | Kind | Rule it enforces |
|---|---|---|
| `KnowledgeVersion` | E | Has a sequence number, change reason, updated metadata, a reference to the previous version, an active marker and an optional diff summary (§7.6). The sequence number only grows. A published version never changes. |
| `KnowledgeChunk` | E | Belongs to exactly one version. Keeps the source item id, version, page or section, heading path, order and inherited metadata (§7.4). Only chunks of the active version are retrievable by default. Retrievability is derived from the item's active version, not stored; a new version supersedes the old chunks (ADR 0009). |
| `SourceReference` | VO | The item, version, heading path and first and last page a chunk was cut from (§7.4). An answer cites it. |
| `DuplicateFlag` | VO | A version repeats another item of the same Node: kind (`DuplicateKind`: exact, near, metadata variant, overlap), the existing item and version, a score from 0 to 1 and an ambiguous mark (§7.7, ADR 0010). A finding, never a decision. |
| `KnowledgeScope` | VO | Domain, confidentiality level and usage scope of an item (§5.3). |
| `VersionTag` | VO | Immutable version id (§5.3). |
| `MetadataRecord` | VO | Structured metadata (§7.5). Shared with Issue Management (shared kernel). |

### Domain events

`KnowledgeItemSubmitted`, `MetadataRecorded`, `DuplicateDetected`, `KnowledgeVersionPublished`, `ThicknessReadingsExtracted`, `CorrosionRateCalculated`, `LessonLearnedExtracted`, `BarrierRegisterUpdated`, `ResolutionStoredAsKnowledge`.

## 3. RAG Core

Spec §8.1 and §8.4. A generic context that supplies retrieval and grounded generation.

### Aggregate root

**`RetrievalRun` (proposed)**

- Key attributes: `RetrievalQuery`, requesting `NodeIdentifier`, allowed scope, ranked chunk ids with `SimilarityScore`, prompt id and version, generated output.
- Invariants:
  - It retrieves only chunks the requesting Node is allowed to see (§8.1 step 3, §8.4).
  - It uses chunks of the active version only (§7.6).
  - Every generated answer carries source references (§8.1 step 10).
  - If the knowledge is not enough, the answer says so instead of guessing (§8.4).

### Entities and value objects

| Name | Kind | Rule it enforces |
|---|---|---|
| `GroundedAnswer` (proposed) | E | An answer is linked to the chunks it was built from. |
| `RetrievalQuery` | VO | Normalized form of a user or system request (§5.3). |
| `SimilarityScore` | VO | Similarity of a chunk to a query. Same scale for vector and hybrid search. |
| `Citation` (proposed) | VO | Points to one `KnowledgeItem`, `VersionTag` and, when known, a page or section. |

### Domain events

`KnowledgeChunksIndexed`, `GroundedAnswerGenerated`.

## 4. Issue Management

Spec §12 and §14. The core of the system.

### Aggregate root

**`Issue`**

- Key attributes: issue id, owner `NodeIdentifier`, title, description, `MetadataRecord`, status, `ProgressPercentage`, its `SubIssue`s.
- Invariants:
  - An Issue has a title and a description and belongs to one Node (§12.1).
  - A new Issue is compared with the existing Issues of the same Node before it is created (§12.1).
  - Progress is calculated from rules over SubIssues, knowledge, Executors, a proposed solution and review status. It is never set freely (§14.1).
  - A SubIssue has its own id, status and progress, and a link to its parent (§12.2). The SubIssue tree has no cycle.
  - A resolved Issue stores its resolution as knowledge.
  - Any possible answer is grounded in sources and states clearly when knowledge is missing (§12.5).
  - A research gap is raised when one of the conditions in §14.3 holds, for example no related knowledge or a judge score below the threshold.

### Entities and value objects

| Name | Kind | Rule it enforces |
|---|---|---|
| `SubIssue` | E | An Issue derived from a parent, with its own status, progress, relative position, related knowledge and candidate Executors (§12.2, §12.3). |
| `ProgressPercentage` | VO | A value from 0 to 100 (§5.3). |
| `IssueStatus` (proposed) | VO | One of the statuses in §14.1: New, Analyzing, Knowledge identified, Executor identified, Solution proposed, In execution, Awaiting decision, Resolved, Unresolved, Archived. The spec gives no transitions (open question 6). |
| `MetadataRecord` | VO | Shared with Knowledge Management. |

### Domain events

`WallLossExceededThreshold`, `RepeatedFailureFlagged` and `BarrierDegradationReported` (these start an Issue), `IssueRaised`, `SimilarIssueFound`, `IssuePrioritized`, `KeyIssueMarked`, `IssueDecomposed`, `RootCauseConfirmed`, `FitnessForServiceAssessed`, `SubIssueProgressUpdated`, `IssueResolved`.

## 5. Executor Management

Spec §13.2. A supporting context.

### Aggregate root

**`Executor`**

- Key attributes: executor id, owner `NodeIdentifier`, kind (person, team, unit or capability, §5.2), organizational role, expertise, project participation, optional availability.
- Invariants:
  - Every claimed expertise comes from evidence: a personnel profile, a past project, an authored document or a past Issue (§13.2). A match explanation cites that evidence (`docs/evaluation-baseline.md`, executor matching).
  - Availability is optional (§13.2).
  - The system only proposes Executors. Assignment is a separate decision in the Issue-Knowledge-Executor Model.

### Entities and value objects

| Name | Kind | Rule it enforces |
|---|---|---|
| `ExpertiseArea` (proposed) | E | One domain the Executor is expert in, with the evidence for it. |
| `ProjectParticipation` (proposed) | E | One past project the Executor worked on (§11.1, §13.2). |
| `ExpertiseTag` (proposed) | VO | A normalized technical domain tag (§13.2). |

### Domain events

`ExecutorCandidatesProposed`.

## 6. Issue-Knowledge-Executor Model

Spec §13. A core context. Where its code lives is not decided (open question 1).

### Aggregate root

**`IKEGraph` (proposed)**

- Key attributes: owner `NodeIdentifier`, links between Issues, KnowledgeItems and Executors.
- Invariants:
  - A link joins existing Issue, KnowledgeItem or Executor ids of the same Node. Cross-Node links are not defined in the spec (open question 5).
  - Each relation type allows only certain endpoint kinds. For example "executor is expert in a domain" starts at an Executor (§13.1) (interpretation).
  - A link of the same type between the same two ends exists once.
  - "Decomposes into" follows the `SubIssue` tree of Issue Management and has no cycle. "Is blocked by" has no cycle (interpretation).
  - A KnowledgeItem can support an answer or limit it, and the two are kept apart (§13.1).
  - The graph is node knowledge. It can go upward only within Layer rules and confidentiality limits (§13.3).

### Entities and value objects

| Name | Kind | Rule it enforces |
|---|---|---|
| `IKELink` (proposed) | E | One typed link with two ends. |
| `RelationType` (proposed) | VO | One of the 12 relation kinds in §13.1. |

### Domain events

`AlertMatchedToEquipment`, `KnowledgeLinkedToIssue`, `ResearchGapIdentified`, `ExecutorAssigned`.

`AlertMatchedToEquipment` refers to equipment, which the spec does not model (open question 4).

## 7. Knowledge Transfer

Spec §9, §10 and §11. A core context.

### Aggregate root

**`TransferPackage`**

- Key attributes: package id, source `NodeIdentifier`, target `LayerIndex`, `TransferDetailLevel`, content items, source references, `JudgeScore` id, state.
- Invariants:
  - A package goes from a lower Layer to a higher one (§5.2).
  - Its detail level matches the level the receiving Layer asks for (§6.4, registry).
  - It follows the receiving Layer's rules on required and excluded topics and maximum length (§10.1).
  - Key claims carry source references, and incomplete knowledge is noted as such (§10.2).
  - It is delivered only after the judge gate passes and it is approved. If the latest package fails the threshold, the previous accepted version is delivered with a warning (§9.2).
  - The latest accepted version is always kept (§9.2). Delivery metadata is recorded.
  - States follow the board: drafted, then accepted or rejected, then approved, then delivered. A rejected package is regenerated or replaced by the previous accepted version.

### Entities and value objects

| Name | Kind | Rule it enforces |
|---|---|---|
| `TransferItem` (proposed) | E | One section of the package, such as an achievement, an Issue status or a research gap (§10.3). |
| `TransferDetailLevel` | VO | Detail level of a package. The wording differs between §5.3 and §6.4 (open question 2). |

### Domain events

`ProcessingCycleTriggered`, `NodeCycleCompleted`, `TransferPackageDrafted`, `TransferPackageAccepted`, `TransferPackageRejected`, `TransferPackageRegenerated`, `TransferPackageApproved`, `PreviousAcceptedVersionReused`, `TransferPackageDelivered`.

## 8. Evaluation and Judging

Spec §16. A core context.

### Aggregate root

**`JudgeScore`**

- Key attributes: judged output reference, `JudgeRubric`, per-criterion points, total out of 20, `JudgeThreshold`, verdict, explanation, missing information, unsupported claims, excessive or insufficient detail, suggested fix.
- Invariants:
  - The total is the sum of the criterion points. Each criterion stays within its maximum, and the default maximums add up to 20 (§16.1).
  - The output is accepted if and only if the total reaches the threshold. The initial threshold is 18/20 for important outputs (§16.1).
  - A score names the rubric it was made with.
  - A failed gate leads to one of: regenerate, more detail, less detail, add citations, human review, or for a `TransferPackage` the last accepted version (§16.2).
  - The judge compares the output with the source knowledge, the user request, the task instruction and the rubric (§16).
  - A judged output is referenced, not copied. The score never changes after it is issued.

### Entities and value objects

| Name | Kind | Rule it enforces |
|---|---|---|
| `CriterionScore` (proposed) | E | Points for one rubric criterion, never above its maximum. |
| `Verdict` (proposed) | VO | Accept or reject (§16.2). |
| `JudgeRubric` | VO | The criteria and their points. Default: faithfulness 5, completeness 4, detail level 3, uncertainty handling 3, clarity 2, citability 2, no unsupported claims 1 (§16.1). See open question 3. |
| `JudgeThreshold` | VO | Minimum acceptable score, 18/20 at first (§5.3, §16.1). |

### Domain events

`OutputJudged`, `JudgeGatePassed`, `JudgeGateFailed`, `HumanReviewRequested`, `TransferPackageJudged`.

## 9. RFP and Proposal

Spec §15. A supporting context.

### Aggregate roots

**`RFP`**

- Key attributes: RFP id, origin Issue id, status, sections from the Issue, its SubIssues, related knowledge, research gaps, requirements, expected outputs, evaluation indicators, constraints, required expertise and documentation (§15.1).
- Invariants:
  - An RFP is linked to the Issue it came from and is stored as a `KnowledgeItem` (§15.1).
  - All mandatory sections are present before it is published (`docs/evaluation-baseline.md`, RFP completeness).
  - A published RFP is not edited. A change is a new version (interpretation).

**`Proposal`**

- Key attributes: proposal id, RFP id, vendor, content, evaluation, `FeedbackReport`.
- Invariants:
  - A Proposal answers one existing RFP and is evaluated only against that RFP's criteria (§15.2).
  - At most one Proposal per RFP is awarded (interpretation, from the board flow).
  - Every point of feedback traces to an RFP criterion or a part of the Proposal (§15.3).

### Entities and value objects

| Name | Kind | Rule it enforces |
|---|---|---|
| `FeedbackReport` | E of `Proposal` | Holds strengths, weaknesses, missing requirements, risks, a suggested score and a recommendation to select, revise or reject (§15.3). |
| `RFPStatus` (proposed) | VO | The state of an RFP, such as draft or published. The values are not in the spec (open question 6). |

### Domain events

`RFPGenerated`, `RFPPublished`, `ProposalReceived`, `ProposalEvaluated`, `FeedbackReportIssued`, `ProposalAwarded`.

## 10. Model and Prompt

Spec §8.2 and §8.3. A generic context. Today it is kept in `models/manifest.yaml` and `prompts/registry.yaml`.

### Aggregate roots

**`PromptTemplate` (proposed)**

- Key attributes: task, versions, expected output format, source citation behavior, linked rubric.
- Invariants:
  - A version never changes. A change to the wording, variables or target model is a new version.
  - Exactly one version per task is active (`prompts/registry.yaml`).
  - The task is one of the 12 categories in §8.3.
  - A prompt that needs citations says so, and the judge checks it.

**`ModelConfig` (proposed)**

- Key attributes: role (embedding, LLM or LVM, §8.2), name, tag, runtime, digest, default parameters, status.
- Invariants:
  - Prompts pick a model by role, never by name (`prompts/registry.yaml`).
  - The model weights are identified by a digest, so a result can be reproduced (`docs/adr/0001-local-models-and-runtime.md`).
  - Default parameters are fixed so that the same input gives the same output.

### Entities and value objects

| Name | Kind | Rule it enforces |
|---|---|---|
| `PromptTestRun` (proposed) | E of `PromptTemplate` | Records one test of one prompt version, so a version change can be compared (§8.3). |
| `ModelParams` (proposed) | VO | Temperature, seed, context size and maximum output size. |

### Domain events

The event storming has no lane for this context, so there are no events yet.

## 11. Repositories

One repository per aggregate root. Each one is a `Protocol` port in `application/ports.py` of its context, with an in-memory fake in `tests/fakes/` (`.claude/CLAUDE.md`). Aggregates are loaded and saved whole.

Rules for all repositories:

- `get_…` raises a not-found error if nothing matches. `find_…` returns `None`, or an empty list for collections.
- `add` stores a new aggregate. `save` stores changes to an existing one.
- A not-found error is in the "Not found" category of `docs/errors.md` (HTTP 404). The codes below are proposals. Each one goes into the catalog in `docs/errors.md` in the same change that adds the error class.
- Ids are the value objects or id types named in the aggregate. `NodeIdentifier` and `LayerIndex` are the published ones.
- Every `find_by_owner` assumes the strict owner rule (open question 5, option a). If the user picks option b or c, these signatures change.
- A repository never joins to another aggregate. Data from other aggregates is read through their own repositories in the application layer.

### Organizational Hierarchy

**`NodeRepository`**

- `get_by_id(node_id: NodeIdentifier) -> Node`. Raises `ORGANIZATION_NODE_NOT_FOUND`.
- `find_children(node_id: NodeIdentifier) -> list[Node]`.
- `add(node: Node) -> None`.
- `save(node: Node) -> None`.

**`LayerRepository`**

- `get_by_index(layer_index: LayerIndex) -> Layer`. Raises `ORGANIZATION_LAYER_NOT_FOUND`.
- `find_all() -> list[Layer]`, ordered by `LayerIndex`.
- `save(layer: Layer) -> None`. The five Layers exist from the start, so there is no `add`. Depends on open question 2 for the wording of the detail level a Layer holds.

### Knowledge Management

**`KnowledgeItemRepository`**

- `get_by_id(item_id: str) -> KnowledgeItem`. Raises `KNOWLEDGE_ITEM_NOT_FOUND`.
- `find_by_owner(node_id: NodeIdentifier) -> list[KnowledgeItem]`.
- `add(item: KnowledgeItem) -> None`.
- A new `KnowledgeVersion` is saved through its item, with its ingestion, in `KnowledgeIngestionRepository.add_with_version` (ADR 0005).

**`VersionFingerprintRepository`** (built)

The exact- and near-duplicate lookups (§7.7, ADR 0010). It returns `VersionFingerprint`s (item, version, owner Node, file hash, normalized text hash, metadata), not whole items.

- `find_by_content_hash(node_id, content_hash) -> list[VersionFingerprint]`: every version of the Node's items with this file hash.
- `find_by_text_hash(node_id, normalized_text_hash) -> list[VersionFingerprint]`.
- `list_active_by_owner(node_id) -> list[VersionFingerprint]`.
- `save_text_hash(item_id, version_tag, normalized_text_hash) -> None`, set when the version is chunked.

**`KnowledgeChunkRepository`** (built)

- `replace(item_id, version_tag, chunks) -> None`, `list_by_version(item_id, version_tag)`, `list_active_by_owner(node_id)`.

**`DuplicateFlagRepository`** (built)

- `replace(item_id, version_tag, flags) -> None`, `list_by_version(item_id, version_tag)`.

Overlap candidates are found lexically, from the word shingles of the Node's active chunks (ADR 0010). Embedding similarity over the vector index can be added as a second source of chunk scores in phase 8. Depends on open question 5 (who owns an item) and open question 4 (no equipment lookup is added).

### RAG Core

**`RetrievalRunRepository` (proposed)**

- `get_by_id(run_id: str) -> RetrievalRun`. Raises `RAG_RETRIEVAL_RUN_NOT_FOUND`.
- `add(run: RetrievalRun) -> None`. A finished run is never changed, so there is no `save`.

This repository exists only if the user approves `RetrievalRun`. It also assumes runs are stored at all, which the spec does not say.

### Issue Management

**`IssueRepository`**

- `get_by_id(issue_id: str) -> Issue`. Raises `ISSUE_NOT_FOUND`.
- `find_by_owner(node_id: NodeIdentifier) -> list[Issue]`. Used to compare a new Issue with the Issues of the same Node (§12.1).
- `add(issue: Issue) -> None`.
- `save(issue: Issue) -> None`. `SubIssue`s are saved through their Issue, unless open question 6 moves them out of the aggregate.

### Executor Management

**`ExecutorRepository`**

- `get_by_id(executor_id: str) -> Executor`. Raises `EXECUTOR_NOT_FOUND`.
- `find_by_owner(node_id: NodeIdentifier) -> list[Executor]`. Used to find candidates (§13.2).
- `add(executor: Executor) -> None`.
- `save(executor: Executor) -> None`.

### Issue-Knowledge-Executor Model

**`IKEGraphRepository` (proposed)**

- `get_by_owner(node_id: NodeIdentifier) -> IKEGraph`. Raises `<CONTEXT>_IKE_GRAPH_NOT_FOUND`. There is one graph per Node.
- `save(graph: IKEGraph) -> None`. It creates the graph the first time.

Depends on open question 1 (the error code prefix and the package follow the context folder) and on open question 5 (cross-Node links).

### Knowledge Transfer

**`TransferPackageRepository`**

- `get_by_id(package_id: str) -> TransferPackage`. Raises `TRANSFER_PACKAGE_NOT_FOUND`.
- `find_latest(source_node_id: NodeIdentifier) -> TransferPackage | None`. The newest package in any state.
- `find_latest_accepted(source_node_id: NodeIdentifier) -> TransferPackage | None`. Used to deliver the last accepted version (§9.2).
- `add(package: TransferPackage) -> None`.
- `save(package: TransferPackage) -> None`. Older packages are kept, never overwritten (§9.2).

### Evaluation and Judging

**`JudgeScoreRepository`**

- `get_by_id(score_id: str) -> JudgeScore`. Raises `EVALUATION_JUDGE_SCORE_NOT_FOUND`.
- `find_by_judged_output(output_reference: str) -> list[JudgeScore]`. A regenerated output may have several scores.
- `add(score: JudgeScore) -> None`. A score never changes once issued, so there is no `save`.

Open question 3 does not change the methods. It changes only the name of the rubric a score keeps.

### RFP and Proposal

**`RFPRepository`**

- `get_by_id(rfp_id: str) -> RFP`. Raises `RFP_NOT_FOUND`.
- `find_by_issue(issue_id: str) -> list[RFP]`. A new version is a new `RFP` for the same Issue (interpretation).
- `add(rfp: RFP) -> None`.
- `save(rfp: RFP) -> None`. Allowed only before it is published.

**`ProposalRepository`**

- `get_by_id(proposal_id: str) -> Proposal`. Raises `RFP_PROPOSAL_NOT_FOUND`.
- `find_by_rfp(rfp_id: str) -> list[Proposal]`. Needed to compare Proposals and to keep one award per RFP.
- `add(proposal: Proposal) -> None`.
- `save(proposal: Proposal) -> None`.

### Model and Prompt

**`PromptTemplateRepository` (proposed)**

- `get_by_task(task: str) -> PromptTemplate`. Raises `MODEL_PROMPT_PROMPT_TEMPLATE_NOT_FOUND`.
- `add(template: PromptTemplate) -> None`.
- `save(template: PromptTemplate) -> None`. It adds a version or changes the active one.

**`ModelConfigRepository` (proposed)**

- `get_by_role(role: str) -> ModelConfig`. Raises `MODEL_PROMPT_MODEL_CONFIG_NOT_FOUND`. Prompts pick a model by role.
- `find_all() -> list[ModelConfig]`.

Today the adapters for both read `prompts/registry.yaml` and `models/manifest.yaml`, so `ModelConfigRepository` has no write methods. The other contexts reach them through ports of their own, such as a model lookup in RAG Core, and not through these repositories.

## 12. Domain services

A domain service holds stateless domain logic that needs more than one aggregate, or that belongs to none. It lives in `domain/` of its context, so it has no I/O and no third-party imports.

Rules for all services:

- A service never calls a model, a store or the clock. If a rule needs a similarity score, a token count or a date, the application layer computes it through a port and passes it in as plain data. This keeps the service pure and testable without fakes.
- The names are technical (detector, calculator, policy). They are not new domain terms. The user can still rename them (open question 7).
- Numeric thresholds that the spec does not give are inputs, not constants (open question 7).

| Service | Context | Pure or needs a port |
|---|---|---|
| `DuplicateDetector` | Knowledge Management | Pure. Similarity scores come in as data. |
| `SimilarIssueDetector` | Issue Management | Pure. Similarity scores come in as data. |
| `IssueProgressCalculator` | Issue Management | Pure. |
| `IssuePrioritizer` | Issue Management | Pure. |
| `ResearchGapDetector` | Issue Management (see open question 1) | Pure. Facts come in as data. |
| `ExecutorMatcher` | Executor Management | Pure. Any semantic score comes in as data. |
| `RetrievalScopePolicy` | RAG Core | Pure. |
| `TransferRuleChecker` | Knowledge Transfer | Pure. Length and topic labels come in as data. |
| `TransferDeliverySelector` | Knowledge Transfer | Pure. |
| `JudgeGatePolicy` | Evaluation and Judging | Pure. |

### `DuplicateDetector`

- Context: Knowledge Management. Spec §7.7, §7.2 step 7. Built in `knowledge/domain/duplicate_detection.py` (ADR 0010).
- Input: a candidate `VersionFingerprint` and `DuplicateComparison`s: for each existing version of the same Node, its fingerprint and, for each candidate chunk, the share of the chunk's shingles found in that version.
- Output: `DuplicateFlag`s, at most one per existing item (the strongest), ordered by item id. An empty list means no duplicate.
- Rule: equal file hash is an exact duplicate. Equal normalized text hash is a near duplicate, or a metadata variant when the `MetadataRecord` differs. When at least a minimum share of chunks reaches the overlap similarity, it is an overlap; when that share is only reached in the gray band below, the overlap is marked ambiguous, so the application layer can later ask the LLM for the final check (§7.7). The candidate's own item and other Nodes' items are skipped.
- Port: none inside the service. The thresholds come from `Settings`. The application layer computes the similarities (lexically for now) and passes them in.
- It never decides what to do with a duplicate. That is open question 6; until then both items are kept.

### `SimilarIssueDetector`

- Context: Issue Management. Spec §12.1 steps 3 and 4, §7.7 last bullet.
- Input: a new Issue (title, description, `MetadataRecord`) and the existing Issues of the same Node, each with a similarity score to the new one.
- Output: a ranked list of existing Issue ids, each marked likely duplicate or overlap.
- Rule: only Issues of the same Node are compared. An Issue is never compared with itself or with its own `SubIssue`s.
- Port: none inside the service. Scores come from the `Embedder`.

### `IssueProgressCalculator`

- Context: Issue Management. Spec §14.1.
- Input: an `Issue` with its `SubIssue`s and plain facts about it: number of supporting knowledge links, whether an Executor is mapped, whether a solution is proposed, whether needed research is complete, whether it was reviewed. The facts about knowledge and Executors come from the Issue-Knowledge-Executor Model and are passed as numbers, because an Issue refers to them by id only.
- Output: a `ProgressPercentage` from 0 to 100, for the Issue and for each `SubIssue`.
- Rule: progress is calculated, never set (§14.1). An Issue with SubIssues also counts their resolution. The weights and the formula are not in the spec (open question 6), so they are an input to the service.
- Pure domain logic.

### `IssuePrioritizer`

- Context: Issue Management. Spec §14.2, §12.3.
- Input: the open Issues of a Node and for each one the factors of §14.2 (strategic importance, urgency, risk level, number of dependent Issues, missing knowledge, impact on projects, importance for the higher Layer, link to RFPs, repetition in several Nodes).
- Output: the Issues in priority order, with the factors that decided each position.
- Rule: the order is reproducible for the same input. The weights are not in the spec, so they are an input. Repetition in several Nodes needs data from other Nodes, so it works only for the owning Node until open question 5 is settled.
- Pure domain logic.

### `ResearchGapDetector`

- Context: Issue Management, because the spec ties it to an Issue (§14.3). The `ResearchGapIdentified` event is on the Issue-Knowledge-Executor lane, so it may move with open question 1.
- Input: an `Issue` and facts about it: number of related knowledge items, age of the newest one, whether the answer is reliable, whether sources conflict, whether Executor expertise is clear, whether a project challenge is unresolved, and the latest `JudgeScore` total with its `JudgeThreshold`.
- Output: the list of reasons that hold, taken from the seven conditions of §14.3. An empty list means no gap.
- Rule: each condition is checked on its own. The `JudgeScore` condition holds when the total is below the threshold.
- Pure domain logic. The age limit for "outdated" is not in the spec (open question 7).

### `ExecutorMatcher`

- Context: Executor Management. Spec §13.2, §12.1 step 9.
- Input: the domain and technical tags of an Issue or `SubIssue` and the Executors of the Node, each with its evidence (profile, past project, authored document, past Issue) and optional availability. A semantic similarity score may be added as data.
- Output: a ranked list of candidate Executor ids. Each candidate carries the evidence that supports it, so the explanation can cite it (`docs/evaluation-baseline.md`).
- Rule: an Executor without evidence is never a candidate. Availability only reorders candidates and never removes one, because it is optional. The service proposes. It never assigns.
- Pure domain logic.

### `RetrievalScopePolicy`

- Context: RAG Core. Spec §8.1 step 3, §8.4, §6.1.
- Input: the requesting `NodeIdentifier`, its `LayerIndex` and its ancestors' ids, and the `KnowledgeScope` of the items.
- Output: the allowed scope, which is a set of owner `NodeIdentifier`s and a highest confidentiality level, to be used as a filter in the search.
- Rule: a Node always sees its own items. Whether it also sees items of other Nodes depends on open question 5 and on the "Confidentiality Per Layer" hotspot in `docs/discovery-report.md`. Both are open, so this service has only the strict owner rule (option a) until the user decides.
- Pure domain logic.

### `TransferRuleChecker`

- Context: Knowledge Transfer, reading the transfer rules of a `Layer`. Spec §10.1, §10.2, §6.4, §5.2.
- Input: a drafted `TransferPackage` (target `LayerIndex`, detail level, items, source references), the receiving `Layer`, and facts the application layer measured: package length, topic label of each item, which key claims have a source reference.
- Output: a list of rule violations, empty when the package follows the rules.
- Rule: the package goes from a lower to a higher Layer. It has the detail level the receiving Layer asks for. All required topics are present and no excluded topic is. The length is within the maximum. Key claims have source references to the level the Layer requires. Incomplete knowledge is noted.
- Port: none inside the service. A tokenizer and a topic classifier (rules, or an LLM) run in the application layer. Depends on open question 2 for the detail level names.

### `TransferDeliverySelector`

- Context: Knowledge Transfer. Spec §9.2, §16.2.
- Input: the `TransferPackage`s of one source Node, each with its state, and its `JudgeScore` result.
- Output: the package to deliver and a flag saying whether it is a fallback with a warning.
- Rule: if the latest package is accepted and approved, deliver it. If it failed the judge gate, deliver the previous accepted one with a warning. If no accepted package exists, nothing is delivered and the caller gets a domain error. Delivery metadata is recorded by the application layer.
- Pure domain logic.

### `JudgeGatePolicy`

- Context: Evaluation and Judging. Spec §16.1, §16.2, §10.1.
- Input: a `JudgeScore` total, the kind of output judged, the minimum judge score of the receiving `Layer` when the output is a `TransferPackage`, the number of regenerations already done, and whether a previous accepted version exists.
- Output: pass, or fail with one next action from §16.2: regenerate, more detail, less detail, add citations, human review, or use the last accepted version.
- Rule: the output passes if and only if the total reaches the threshold. The threshold is the default 18/20 for important outputs, or the Layer's minimum when it is set. Which one wins is open question 6, so the choice is an input. The suggested fix of the judge picks among detail and citation actions. Human review is the action when no other one is left.
- Pure domain logic. The `JudgeScore` itself computes the total and its own verdict. This service decides only what follows.

### Rules that are not services

These rules sit inside an aggregate, so they are not services:

- The parent of a `Node` is in a higher Layer. `Node` receives the parent's `LayerIndex` as data when it is registered.
- The total of a `JudgeScore` and its accept or reject verdict.
- The cycle check of the `SubIssue` tree.
- The mandatory sections of an `RFP` before publishing.
- Feedback in a `FeedbackReport` traces to an RFP criterion.

Proposal evaluation (§15.2) and the generation of an answer, an RFP or a package are not domain services. They call a model, so they are use cases in the application layer.

## Open questions

These belong to the user. None of them is settled here.

1. **Where the Issue-Knowledge-Executor context lives in code.** The context table says `executor`, `issue` and `knowledge`, undecided.
   - (a) A new folder `ike`.
   - (b) Inside `issue`, since an Issue is the center of every link.
   - (c) Inside `executor`.
   - (d) Split by the three kinds of link, one per context.
2. **`TransferDetailLevel` wording.** Spec §5.3 says management, executive, technical and detailed technical. Spec §6.4 says top executive, managerial, technical summary and detailed technical. The registry uses `top_executive`, `managerial`, `technical_summary` and `detailed_technical`.
   - (a) Use the §6.4 set everywhere.
   - (b) Use the §5.3 set.
   - (c) Keep two names, one per use.
3. **`JudgeRubric` or `Rubric`.** Spec §5.3 says `JudgeRubric`. The naming rules list `Rubric`.
   - (a) `JudgeRubric` (spec §5.3).
   - (b) `Rubric` (naming rules and the registry file `prompts/rubrics/`).
   - (c) Both, with `Rubric` as the definition and `JudgeRubric` as its use by the judge.
4. **Asset or equipment concept.** The board mentions risers, pumps and an Asset Integrity Register, and `AlertMatchedToEquipment` needs a target.
   - (a) No new concept. Equipment is a tag in `MetadataRecord`.
   - (b) A new entity inside Knowledge Management.
   - (c) A new aggregate, with its own context or inside Knowledge Management.
5. **Node scope rule.** What does a Node own, and what may cross its edge?
   - (a) A strict owner. Every `KnowledgeItem`, Issue and Executor belongs to exactly one Node, and nothing is shared.
   - (b) An owner plus read access for ancestor Nodes within Layer rules and confidentiality limits.
   - (c) The same `KnowledgeItem` may be held by several Nodes. This also settles the "Cross-Node Duplicates" hotspot.
6. **Gaps found while writing this model** (the spec is silent, so the model lists them and does not guess):
   - What happens to an exact or near duplicate: reject, link or keep both.
   - Allowed `IssueStatus` transitions and the progress formula (§14.1).
   - How many times a failed output is regenerated, and which threshold wins among §10.1, §16.1 and §16.2.
   - The values of `RFPStatus`.
   - Whether a `SubIssue` inside the `Issue` aggregate is right, since the spec says a SubIssue is an Issue with its own state (§12.2).
   - A name for the transfer rules of a `Layer` if they need to be a concept of their own.
7. **Names and numbers for the domain services** (new in section 12):
   - Confirm or rename the service names. They are technical names, not domain terms.
   - The spec gives no numbers for the near-duplicate similarity, the similar-Issue similarity, the age at which knowledge is "outdated" (§14.3), the confidence below which an Issue "cannot be answered reliably", or the weights of progress and priority. Decide whether they live in `Settings`, in the transfer rules of a `Layer`, or in a rule table kept in the repository.
8. **Whether a `RetrievalRun` is stored at all.** The spec asks for source references on every answer, but not for a record of each run. If runs are not stored, `RetrievalRunRepository (proposed)` is dropped.
