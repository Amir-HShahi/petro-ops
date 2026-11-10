# Application services

This document is the use-case catalog for phase 3 (application service boundaries, spec phase plan after §18). It lists, for each bounded context, the use cases the application layer will offer, what each one touches and which phase builds it.

Sources:

- The commands (blue stickies) on the "event-storming" page of the Lucid board PetroOps. There are 25.
- Spec §5 to §16 in `docs/project-fa.md`, and the phase plan after §18.
- `docs/domain-model.md` for aggregates, events (section by context), repositories (section 11) and domain services (section 12). This file does not repeat them.
- The "application-services" page of the Lucid board shows the same catalog as a diagram.

## What an application service is here

- A use case is one action in one context. It is one **command** (a frozen dataclass in `application/commands.py`) and one **handler** (`application/<use_case>.py`). See the `new-use-case` skill.
- The handler only coordinates. It loads an aggregate through a repository, calls domain code (aggregates and domain services), saves it and publishes the events. Business rules stay in `domain/`.
- The handler depends on `domain/` and on ports. It never imports `infrastructure/`.
- Ports are `Protocol`s in the context's `application/ports.py`. Each has an in-memory fake in `tests/fakes/`.
- One handler call is one transaction on one aggregate. Aggregates refer to each other by id only. Work across aggregates or contexts is done by events (see "Cross-context flows").
- `src/offline_rag/bootstrap.py` is the only place that picks adapters, opens transactions and subscribes handlers to events. It is not created yet.
- Read models of the board (Knowledge Inventory, Open Issues Board, IKE Graph View, Proposal Comparison, Judge Score Card, Platform Risk Summary, Asset Integrity Register) are queries, not commands. They are not listed here.

## How to read the tables

- **Command** is an imperative name. The name is the board label without spaces. **(added)** means the command is not on the board. It was added because an event on the board or a spec requirement has no command. **(proposed)** is as in `docs/domain-model.md`: the name is not approved and must not enter code yet.
- **Aggregate** is the one aggregate the handler changes. "Reads" means it is only read.
- **Ports** are named by role. Repositories are named `<AggregateRoot>Repository`. The shared ports of the next section are used in the same way.
- **Phase** is from the spec phase plan. "Unscheduled" means the spec plan has no phase for it because the use case comes from the offshore scenario only.
- `EventPublisher` and `IdGenerator` are implicit in every handler and are not repeated. `Clock` is listed where the use case stamps a time.
- "OQ n" is open question n in `docs/domain-model.md`. "AOQ n" is an open question in this file.

## Shared ports

| Port | Role | Used for |
|---|---|---|
| `Embedder` | Turns text into vectors | Duplicate checks, similar Issue check, retrieval |
| `LLM` | Generates text | Answers, decomposition, RFPs, packages, judging |
| `DocumentParser` | Reads DOC, DOCX and PDF into text, tables and page references | Ingestion |
| `VectorIndex` | Stores and searches chunk vectors with metadata filters | Near duplicates, retrieval |
| `Clock` | Current time | Version, approval and delivery times |
| `Tokenizer` | Counts tokens | Package length, chunk size |
| `TransferChannel` | Carries a `TransferPackage` to the higher Layer (offline channel, CSV output) | Delivery |
| `PromptCatalog` | Looks up the active prompt for a task and the rubric for a judge task | Every use case that calls the `LLM` |
| `NodeDirectory` | Reads a `Node` and the transfer rules of its `Layer` | Owner check, package rules |
| `KnowledgeReader` | Reads `KnowledgeItem`s and chunks of another context | Context assembly |
| `IssueReader` | Reads an Issue and its SubIssues of another context | RFP, links, matching |
| `ExecutorReader` | Reads Executors of another context | Assignment |
| `IKEGraphReader` (proposed) | Reads links of the Issue-Knowledge-Executor model | Progress, priority, RFP |
| `JudgeScoreReader` | Reads the latest `JudgeScore` of an output | Gate decisions, gap detection |

The six reader and directory ports (`NodeDirectory` to `JudgeScoreReader`) are the only way a context reads data of another context. Each is declared in the consuming context. Its adapter in `infrastructure/` calls the query side of the owning context. This keeps the import-linter contracts valid. These are technical names, not domain terms (AOQ 1).

## Counts

| Context | Use cases | On the board | Added |
|---|---|---|---|
| Organizational Hierarchy | 2 | 2 | 0 |
| Knowledge Management | 7 | 3 | 4 |
| RAG Core | 2 | 1 | 1 |
| Issue Management | 8 | 6 | 2 |
| Executor Management | 2 | 1 | 1 |
| Issue-Knowledge-Executor Model | 4 | 3 | 1 |
| Knowledge Transfer | 9 | 4 | 5 |
| Evaluation and Judging | 2 | 2 | 0 |
| RFP and Proposal | 5 | 3 | 2 |
| Model and Prompt | 3 | 0 | 3 |
| **Total** | **44** | **25** | **19** |

## 1. Organizational Hierarchy (`organization`, supporting)

| Command | Inputs | Aggregate | Ports | Events | Phase |
|---|---|---|---|---|---|
| `RegisterNode` | `NodeIdentifier`, name, `LayerIndex`, parent `NodeIdentifier`, activity area, reporting rule, confidentiality limit, `is_internal_structure_tracked` | `Node` | `NodeRepository`, `LayerRepository` | `NodeRegistered` | 6 |
| `DefineTransferRule` | `LayerIndex`, required and excluded topics, detail level, output format, minimum judge score, maximum package length, source reference level | `Layer` | `LayerRepository` | `LayerTransferRuleDefined` | 6 |

- `RegisterNode` reads the parent through `NodeRepository` and passes the parent's `LayerIndex` to the `Node` (domain-model, "Rules that are not services").
- `DefineTransferRule` depends on OQ 2 (detail level wording) and on the open naming of the transfer rules (OQ 6, last bullet).

## 2. Knowledge Management (`knowledge`, core)

| Command | Inputs | Aggregate | Ports | Events | Phase |
|---|---|---|---|---|---|
| `SubmitKnowledgeItem` | owner `NodeIdentifier`, source file, `KnowledgeScope`, `MetadataRecord` | `KnowledgeItem` | `KnowledgeIngestionRepository`, `NodeDirectory`, `SourceFileStore`, `VersionFingerprintRepository` | `KnowledgeItemSubmitted`, `MetadataRecorded`, `DuplicateDetected` | 4 (exact duplicate check 5) |
| `PublishKnowledgeVersion` | item id, new source file, change reason, optional updated `MetadataRecord`, optional diff summary | `KnowledgeItem` | `KnowledgeItemRepository`, `KnowledgeIngestionRepository`, `SourceFileStore`, `VersionFingerprintRepository`, `Clock` | `KnowledgeVersionPublished`, `MetadataRecorded`, `DuplicateDetected` | 5 |
| `ChunkKnowledgeContent` (added) | ingestion id | `KnowledgeIngestion` | `ExtractedContentRepository`, `KnowledgeChunkRepository`, `VersionFingerprintRepository`, `DuplicateFlagRepository`, `Tokenizer` | `DuplicateDetected` | 5 |
| `ExtractThicknessReadings` (added) | item id, `VersionTag` | `KnowledgeItem` | `KnowledgeItemRepository`, `DocumentParser`, `LLM` | `ThicknessReadingsExtracted` | Unscheduled |
| `CalculateCorrosionRate` | item id, `VersionTag` | `KnowledgeItem` | `KnowledgeItemRepository`, `Clock` | `CorrosionRateCalculated` | Unscheduled |
| `ExtractLessonLearned` (added) | item id, `VersionTag` | `KnowledgeItem` | `KnowledgeItemRepository`, `LLM`, `PromptCatalog` | `LessonLearnedExtracted` | Unscheduled |
| `StoreResolutionAsKnowledge` (added) | Issue id, owner `NodeIdentifier`, resolution text | `KnowledgeItem` | `KnowledgeItemRepository`, `IssueReader`, `Clock` | `ResolutionStoredAsKnowledge` | 7 |

- `SubmitKnowledgeItem` and `PublishKnowledgeVersion` use the `DuplicateDetector` for the exact check by file hash, before the file is parsed. A duplicate is flagged and still stored (ADR 0010). What to do with a duplicate is OQ 6. The owner rule is OQ 5.
- `ChunkKnowledgeContent` runs in the chunking worker after extraction (ADR 0005, ADR 0009). It cuts the content into `KnowledgeChunk`s, stores the normalized text hash and runs the `DuplicateDetector` again for near duplicates, metadata variants and overlaps against the Node's other items (ADR 0010). Ambiguous overlaps are only marked; the `LLM` check of the ambiguous band waits for phase 8. Flags are read through the ingestion status query.
- `PublishKnowledgeVersion` refuses a blank change reason (`KNOWLEDGE_VERSION_CHANGE_REASON_MISSING`) and a file identical to the active version (`KNOWLEDGE_VERSION_UNCHANGED`). The new version becomes active at once; the old version's chunks stay stored but are no longer retrievable. Without new metadata it keeps the previous version's.
- `SubmitKnowledgeItem` is also the entry for generated content. A published RFP and a kept RAG answer are stored by calling it (spec §8.1, §15.1).
- `ThicknessReadingsExtracted`, `CorrosionRateCalculated` and `LessonLearnedExtracted` are on the board, but the spec has no thickness, corrosion or lessons learned concept. Where the results are stored depends on OQ 4. These three use cases wait for that decision.
- `BarrierRegisterUpdated` is on the board with no command and no spec basis. It depends on OQ 4 (AOQ 4).

## 3. RAG Core (`rag`, generic)

| Command | Inputs | Aggregate | Ports | Events | Phase |
|---|---|---|---|---|---|
| `IndexKnowledgeChunks` (added) | item id, `VersionTag` | None (writes the vector index) | `KnowledgeReader`, `Embedder`, `VectorIndex` | `KnowledgeChunksIndexed` | 8 |
| `RequestGroundedAnswer` | requesting `NodeIdentifier`, question as `RetrievalQuery`, optional metadata filters | `RetrievalRun` (proposed) | `RetrievalRunRepository` (proposed), `Embedder`, `VectorIndex`, `LLM`, `PromptCatalog`, `NodeDirectory` | `GroundedAnswerGenerated` | 8 |

- `RequestGroundedAnswer` uses the `RetrievalScopePolicy` domain service to build the search filter. Only the strict owner rule exists until OQ 5 and the "Confidentiality Per Layer" hotspot are decided.
- `RetrievalRunRepository` exists only if `RetrievalRun` is approved and runs are stored at all (OQ 8). If not, the handler returns the answer and the port is dropped.
- Chunks are created in Knowledge Management (phases 4 and 5). Indexing is here because the vectors belong to retrieval.

## 4. Issue Management (`issue`, core)

| Command | Inputs | Aggregate | Ports | Events | Phase |
|---|---|---|---|---|---|
| `RaiseIssue` | owner `NodeIdentifier`, title, description, `MetadataRecord`, optional trigger event | `Issue` | `IssueRepository`, `NodeDirectory`, `Embedder` | `IssueRaised`, `SimilarIssueFound` | 7 |
| `SetIssuePriority` | Issue id, priority | `Issue` | `IssueRepository` | `IssuePrioritized` | 7 |
| `MarkKeyIssue` (added) | owner `NodeIdentifier` | `Issue` | `IssueRepository`, `IKEGraphReader` (proposed) | `KeyIssueMarked` | 12 |
| `DecomposeIssue` | Issue id | `Issue` | `IssueRepository`, `LLM`, `PromptCatalog` | `IssueDecomposed` | 7 |
| `ConfirmRootCause` | Issue id, root cause statement, evidence references | `Issue` | `IssueRepository` | `RootCauseConfirmed` | Unscheduled |
| `AssessFitnessForService` (added) | Issue id, assessment result | `Issue` | `IssueRepository` | `FitnessForServiceAssessed` | Unscheduled |
| `UpdateSubIssueProgress` | Issue id, SubIssue id, new facts about the SubIssue | `Issue` | `IssueRepository`, `IKEGraphReader` (proposed) | `SubIssueProgressUpdated` | 7 |
| `ResolveIssue` | Issue id, resolution summary | `Issue` | `IssueRepository`, `Clock` | `IssueResolved` | 7 |

- `RaiseIssue` uses `SimilarIssueDetector`. The `Embedder` supplies the scores, and the handler passes them in. A new Issue is compared with the Issues of the same Node before it is created (spec §12.1).
- `WallLossExceededThreshold`, `RepeatedFailureFlagged` and `BarrierDegradationReported` start `RaiseIssue`. No command on the board emits them (AOQ 4).
- `SetIssuePriority` takes a priority whose type the spec does not define (AOQ 5). `MarkKeyIssue` uses `IssuePrioritizer`.
- `UpdateSubIssueProgress` never sets progress. It passes facts to `IssueProgressCalculator`. The formula is OQ 6 and the board hotspot "Progress Rule Conflict".
- `DecomposeIssue` also asks the `LLM` for SubIssue candidates. A human may accept them. The SubIssue tree is part of the `Issue` aggregate unless OQ 6 moves it out.
- Root cause and fitness for service are not in the spec. They come from the offshore scenario. They stay unscheduled until the user decides they are in scope.
- `ResolveIssue` hands the resolution over by event. Knowledge Management stores it (`StoreResolutionAsKnowledge`).

## 5. Executor Management (`executor`, supporting)

| Command | Inputs | Aggregate | Ports | Events | Phase |
|---|---|---|---|---|---|
| `RegisterExecutor` (added) | owner `NodeIdentifier`, kind, organizational role, expertise with evidence, optional availability | `Executor` | `ExecutorRepository`, `NodeDirectory`, `KnowledgeReader` | None on the board | 9 |
| `ProposeExecutors` | Issue or SubIssue id, domain and technical tags | `Executor` (reads) | `ExecutorRepository`, `IssueReader`, `Embedder` | `ExecutorCandidatesProposed` | 9 |

- `ProposeExecutors` uses `ExecutorMatcher`. It proposes only and never assigns. Assignment is `AssignExecutor` in the Issue-Knowledge-Executor Model. It changes no `Executor` state, so the aggregate is read only.
- `RegisterExecutor` needs an event (AOQ 4). The `KnowledgeReader` checks that the evidence exists.

## 6. Issue-Knowledge-Executor Model (code folder undecided, core)

The code folder is OQ 1. The ports below move with it, and so do the error code prefixes. Every use case here depends on OQ 1 and on cross-Node links (OQ 5).

| Command | Inputs | Aggregate | Ports | Events | Phase |
|---|---|---|---|---|---|
| `MatchAlertToEquipment` | alert `KnowledgeItem` id, equipment tag | `IKEGraph` (proposed) | `IKEGraphRepository` (proposed), `KnowledgeReader`, `Embedder`, `Clock` | `AlertMatchedToEquipment` | Unscheduled (discovery report: 8) |
| `LinkKnowledgeToIssue` | Issue id, `KnowledgeItem` id, relation kind (`RelationType`, proposed) | `IKEGraph` (proposed) | `IKEGraphRepository` (proposed), `IssueReader`, `KnowledgeReader`, `Embedder`, `VectorIndex` | `KnowledgeLinkedToIssue` | 9 |
| `IdentifyResearchGap` (added) | Issue id | `IKEGraph` (proposed) | `IKEGraphRepository` (proposed), `IssueReader`, `KnowledgeReader`, `JudgeScoreReader` | `ResearchGapIdentified` | 12 |
| `AssignExecutor` | Issue or SubIssue id, `Executor` id | `IKEGraph` (proposed) | `IKEGraphRepository` (proposed), `IssueReader`, `ExecutorReader` | `ExecutorAssigned` | 9 |

- `MatchAlertToEquipment` also depends on OQ 4 (no equipment concept) and on the "Alert Freshness" hotspot. It is not in the spec phase plan.
- `LinkKnowledgeToIssue` keeps "supports" and "limits" links apart (spec §13.1).
- `IdentifyResearchGap` uses `ResearchGapDetector`, which sits in Issue Management in the domain model. The aggregate it changes may be `Issue` instead of `IKEGraph` (OQ 1).

## 7. Knowledge Transfer (`transfer`, core)

| Command | Inputs | Aggregate | Ports | Events | Phase |
|---|---|---|---|---|---|
| `TriggerProcessingCycle` | source `NodeIdentifier` (from the scheduler) | None (starts the cycle) | `NodeDirectory`, `Clock` | `ProcessingCycleTriggered`, `NodeCycleCompleted` | 11 |
| `DraftTransferPackage` | source `NodeIdentifier`, cycle reference | `TransferPackage` | `TransferPackageRepository`, `NodeDirectory`, `KnowledgeReader`, `IssueReader`, `LLM`, `PromptCatalog`, `Tokenizer`, `Clock` | `TransferPackageDrafted` | 11 |
| `AcceptTransferPackage` (added) | package id | `TransferPackage` | `TransferPackageRepository`, `JudgeScoreReader` | `TransferPackageAccepted` | 11 |
| `RejectTransferPackage` (added) | package id | `TransferPackage` | `TransferPackageRepository`, `JudgeScoreReader` | `TransferPackageRejected` | 11 |
| `RegenerateTransferPackage` (added) | rejected package id | `TransferPackage` | `TransferPackageRepository`, `NodeDirectory`, `KnowledgeReader`, `IssueReader`, `LLM`, `PromptCatalog`, `JudgeScoreReader`, `Tokenizer` | `TransferPackageRegenerated` | 11 |
| `ReusePreviousAcceptedTransferPackage` (added) | rejected package id | `TransferPackage` | `TransferPackageRepository` | `PreviousAcceptedVersionReused` | 11 |
| `ApproveTransferPackage` | package id, approver | `TransferPackage` | `TransferPackageRepository`, `Clock` | `TransferPackageApproved` | 11 |
| `DeliverTransferPackage` | source `NodeIdentifier` | `TransferPackage` | `TransferPackageRepository`, `TransferChannel`, `Clock` | `TransferPackageDelivered` | 11 |
| `SuggestTransferImprovements` (added) | package id | `TransferPackage` (reads) | `TransferPackageRepository`, `KnowledgeReader`, `LLM`, `PromptCatalog` | None on the board | 11 |

- `DraftTransferPackage` uses `TransferRuleChecker`. The `Tokenizer` and the topic labels are measured in the handler and passed in as data.
- `AcceptTransferPackage` and `RejectTransferPackage` are started by the judge result (`JudgeGatePassed`, `JudgeGateFailed`). Which one follows is the decision of `JudgeGatePolicy` in Evaluation and Judging.
- `RegenerateTransferPackage` and `ReusePreviousAcceptedTransferPackage` are the two ways out of a rejection (spec §9.2, §16.2). The retry limit and the threshold that wins are OQ 6.
- `DeliverTransferPackage` uses `TransferDeliverySelector`. It delivers the last accepted version with a warning if the latest one failed. The `TransferChannel` has a CSV adapter and a database adapter (phase 11 and 15). Delivery to the offline channel uses the same port.
- `TriggerProcessingCycle` runs the cycle of one Node by calling the handlers of the other contexts. The "Urgent Push Offline" hotspot has no use case yet.
- `DraftTransferPackage` and `RegenerateTransferPackage` depend on OQ 2 (detail level names) and the hotspot "Confidentiality Per Layer".

## 8. Evaluation and Judging (`evaluation`, core)

| Command | Inputs | Aggregate | Ports | Events | Phase |
|---|---|---|---|---|---|
| `JudgeOutput` | judged output reference, kind of output, source knowledge references, user request, task instruction, judge task | `JudgeScore` | `JudgeScoreRepository`, `LLM`, `PromptCatalog`, `KnowledgeReader`, `NodeDirectory` | `OutputJudged`, `JudgeGatePassed` or `JudgeGateFailed`, `TransferPackageJudged` (only for a `TransferPackage`) | 10 |
| `RequestHumanReview` | `JudgeScore` id, reason | `JudgeScore` (reads) | `JudgeScoreRepository`, `Clock` | `HumanReviewRequested` | 10 |

- `JudgeOutput` parses the judge's text into criterion points in the handler and builds the `JudgeScore`. The total, the verdict and `JudgeGatePolicy` are domain code. `NodeDirectory` supplies the minimum judge score of the receiving `Layer` when the output is a `TransferPackage`.
- A `JudgeScore` never changes, so `RequestHumanReview` only reads it. The review request itself is an event.
- Threshold handling (spec phase 10) is not a use case. The default 18/20 and the per-Layer minimum come from `Settings` and `DefineTransferRule`. Which one wins is OQ 6 and OQ 7.
- The rubric name depends on OQ 3. The hotspot "Who Checks Judge" has no use case yet.

## 9. RFP and Proposal (`rfp`, supporting)

| Command | Inputs | Aggregate | Ports | Events | Phase |
|---|---|---|---|---|---|
| `GenerateRFP` | Issue id | `RFP` | `RFPRepository`, `IssueReader`, `KnowledgeReader`, `IKEGraphReader` (proposed), `LLM`, `PromptCatalog`, `Clock` | `RFPGenerated` | 13 |
| `PublishRFP` | RFP id | `RFP` | `RFPRepository`, `Clock` | `RFPPublished` | 13 |
| `ReceiveProposal` (added) | RFP id, vendor, source file | `Proposal` | `ProposalRepository`, `RFPRepository`, `DocumentParser`, `Clock` | `ProposalReceived` | 13 |
| `EvaluateProposal` | Proposal id | `Proposal` | `ProposalRepository`, `RFPRepository`, `LLM`, `PromptCatalog` | `ProposalEvaluated`, `FeedbackReportIssued` | 13 |
| `AwardProposal` (added) | Proposal id | `Proposal` | `ProposalRepository`, `RFPRepository`, `Clock` | `ProposalAwarded` | 13 |

- `GenerateRFP` is started by a research gap (`ResearchGapIdentified`). It checks the mandatory sections before `PublishRFP` is allowed.
- A published RFP, and an evaluated Proposal, go into the node's knowledge by calling `SubmitKnowledgeItem` (spec §15, phase 13).
- `EvaluateProposal` is a use case, not a domain service, because it calls a model. It uses the evaluation criteria of the RFP.
- `AwardProposal` keeps one award per RFP through `ProposalRepository.find_by_rfp`. The `RFPStatus` values are OQ 6.

## 10. Model and Prompt (`model_prompt`, generic)

The board has no lane for this context. The use cases come from spec §8.2 and §8.3. Both aggregates are proposed names, so everything here is proposed. Lookups of the active prompt and the model by other contexts are queries (`PromptCatalog`), not commands. `ModelConfigRepository` has no write methods today (domain-model section 11), so there is no command to register a model.

| Command | Inputs | Aggregate | Ports | Events | Phase |
|---|---|---|---|---|---|
| `AddPromptVersion` | task, new template text, variables, target model role, output format | `PromptTemplate` (proposed) | `PromptTemplateRepository` (proposed) | None | 14 |
| `ActivatePromptVersion` | task, version | `PromptTemplate` (proposed) | `PromptTemplateRepository` (proposed) | None | 14 |
| `TestPromptVersion` | task, version, sample scenarios | `PromptTemplate` (proposed) | `PromptTemplateRepository` (proposed), `ModelConfigRepository` (proposed), `LLM`, `Clock` | None | 14 |

- The registries `prompts/registry.yaml` and `models/manifest.yaml` exist since phase 2. Phases 4 to 13 only read them, through `PromptCatalog`.
- `AddPromptVersion` follows the `add-prompt-version` skill. `TestPromptVersion` records a `PromptTestRun` (proposed) inside the template.

## Cross-context flows

Events that another context consumes. A handler in the consuming context is subscribed in `bootstrap.py`. This is the grey "policy" sticky on the board. The default is in-process and synchronous (AOQ 3).

| Event | Emitted by | Consumed by | Reaction |
|---|---|---|---|
| `KnowledgeVersionPublished` | `PublishKnowledgeVersion` | RAG Core | `IndexKnowledgeChunks` |
| `KnowledgeVersionPublished` | `PublishKnowledgeVersion` | Knowledge Management | `ExtractThicknessReadings`, `ExtractLessonLearned` |
| `ThicknessReadingsExtracted` | `ExtractThicknessReadings` | Knowledge Management | `CalculateCorrosionRate` |
| `CorrosionRateCalculated` | `CalculateCorrosionRate` | Issue Management | `RaiseIssue` ("Then Raise Issue") |
| `CorrosionRateCalculated` | `CalculateCorrosionRate` | IKE Model | `MatchAlertToEquipment` ("Then Match Alert") |
| `IssueRaised` | `RaiseIssue` | Issue Management | `DecomposeIssue` ("Then Decompose Issue"; the board draws this policy under `SimilarIssueFound`) |
| `IssueDecomposed` | `DecomposeIssue` | IKE Model, Executor Management | `LinkKnowledgeToIssue`, `ProposeExecutors` ("Then Link And Propose") |
| `ExecutorCandidatesProposed` | `ProposeExecutors` | IKE Model | Waits for a person to call `AssignExecutor` |
| `IssueResolved` | `ResolveIssue` | Knowledge Management | `StoreResolutionAsKnowledge` |
| `ResearchGapIdentified` | `IdentifyResearchGap` | RFP and Proposal | `GenerateRFP` ("Gap Then Generate RFP") |
| `GroundedAnswerGenerated`, `RFPGenerated`, `ProposalEvaluated`, `TransferPackageDrafted` | RAG Core, RFP and Proposal, Knowledge Transfer | Evaluation and Judging | `JudgeOutput` ("Output Then Judge") |
| `JudgeGateFailed` | `JudgeOutput` | Evaluation and Judging | `RequestHumanReview` ("Fail Then Human Review") |
| `JudgeGatePassed` / `JudgeGateFailed` | `JudgeOutput` | Knowledge Transfer | `AcceptTransferPackage` / `RejectTransferPackage` |
| `TransferPackageRejected` | `RejectTransferPackage` | Knowledge Transfer | `RegenerateTransferPackage` or `ReusePreviousAcceptedTransferPackage` |
| `ProcessingCycleTriggered` | `TriggerProcessingCycle` | Knowledge Transfer | `DraftTransferPackage` ("Then Draft Package") |
| `TransferPackageApproved` | `ApproveTransferPackage` | Knowledge Transfer | `DeliverTransferPackage` ("Approved Then Deliver") |
| `RFPPublished`, `ProposalEvaluated` | `PublishRFP`, `EvaluateProposal` | Knowledge Management | `SubmitKnowledgeItem` with the generated content |
| `ProposalReceived` | `ReceiveProposal` | RFP and Proposal | `EvaluateProposal` ("Then Evaluate Proposal") |

## Open questions

The questions of the domain model (OQ 1 to 8) still hold. These are new ones from this catalog. They belong to the user.

1. **AOQ 1: Reader and directory port names.** `NodeDirectory`, `KnowledgeReader`, `IssueReader`, `ExecutorReader`, `IKEGraphReader`, `JudgeScoreReader` and `PromptCatalog` are technical names for read-only ports between contexts. Confirm or rename them. The alternative is one shared query module, which the import-linter contracts would not allow.
2. **AOQ 2: The 18 added commands.** They have no blue sticky on the board. Confirm, drop or merge them (for example, `AcceptTransferPackage` and `RejectTransferPackage` could be one command). If confirmed, the board should get the stickies in the next event storming.
3. **AOQ 3: How events travel.** The default here is an in-process publisher called after the aggregate is saved, with handlers subscribed in `bootstrap.py`. The alternative is an outbox table, which is only worth it if a crash between save and publish must never lose an event.
4. **AOQ 4: Events with no command and no spec basis.** `WallLossExceededThreshold`, `RepeatedFailureFlagged`, `BarrierDegradationReported` (what raises them), `BarrierRegisterUpdated`, and the events of `RegisterExecutor` and `SuggestTransferImprovements`. Decide who emits them or drop them. Several depend on OQ 4.
5. **AOQ 5: Priority value.** The spec names a priority on an Issue but gives no scale. `SetIssuePriority` and `IssuePrioritizer` need a value type. A new type needs a name from the user.
6. **AOQ 6: Scenario-only use cases.** `ConfirmRootCause`, `AssessFitnessForService`, `ExtractThicknessReadings`, `CalculateCorrosionRate`, `ExtractLessonLearned` and `MatchAlertToEquipment` are not in the spec or its phase plan. Decide whether they are in scope and in which phase.
7. **AOQ 7: Model and Prompt commands.** Phase 14 tunes prompts, but earlier phases already need them. Confirm that prompt versions stay files managed by the `add-prompt-version` skill until phase 14, and that the commands in section 10 arrive then.

Use cases that depend on a domain model open question:

| Use case | Depends on |
|---|---|
| `DefineTransferRule` | OQ 2, OQ 6 |
| `SubmitKnowledgeItem` | OQ 5, OQ 6 (duplicate action) |
| `RequestGroundedAnswer` | OQ 5, OQ 8 |
| `UpdateSubIssueProgress`, `RaiseIssue` | OQ 6 (progress formula, status transitions), OQ 7 (thresholds) |
| All of section 6 | OQ 1, OQ 5; `MatchAlertToEquipment` also OQ 4 |
| `DraftTransferPackage`, `RegenerateTransferPackage` | OQ 2, OQ 6 |
| `JudgeOutput` | OQ 3, OQ 6 |
| Extraction and corrosion use cases | OQ 4 |
