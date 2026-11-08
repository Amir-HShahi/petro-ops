# Offline Hierarchical RAG Core

Source of truth for scope and domain terms: `docs/project-fa.md` (Persian; ask the `spec-analyst` agent instead of reading it whole).

## Project structure

```
src/offline_rag/
  shared_kernel/        base types and error categories shared by all contexts
  settings.py           the only place that reads environment variables
  bootstrap.py          wires ports to adapters (not created yet)
  <context>/            organization, knowledge, issue, executor, transfer,
                        rfp, evaluation, model_prompt, rag
    domain/             entities, value objects, domain errors; no I/O
    application/        use cases, commands, ports.py
    infrastructure/     adapters: models, stores, parsers
    interface/          CLI / API entry points
tests/
  unit/<context>/       domain + application with fakes
  integration/<context>/ real adapters
  smoke/ regression/ e2e/
  fakes/                in-memory implementations of ports
prompts/<task>/vN.md    versioned prompt templates + registry.yaml
fixtures/docs, golden/  small sample files and the golden Q&A set
models/                 local model weights, not in git
docs/                   project-fa.md (spec), errors.md (error contract), adr/
scripts/                repo maintenance scripts
docker/                 container files (empty for now)
.github/workflows/      ci, pr-title, claude-review, release-please, release-build
```

Context folders are empty until their first use case; the `new-bounded-context` skill adds the `__init__.py` files and the import-linter contract.

## Stack
- Python 3.12, `uv`, `ruff`, `mypy --strict`, `pytest`, `import-linter`.
- Fully offline: never add cloud SDKs or remote API calls. Runtime sockets go only to loopback services (Ollama, Postgres, RabbitMQ, the API), enforced in `Settings` (ADR 0005).

## Architecture (DDD + hexagonal)
- Code lives in `src/offline_rag/<bounded_context>/` with layers: `domain/` → `application/` → `infrastructure/` → `interface/`.
- `domain/` has no I/O and no third-party imports.
- Every model, store, or parser sits behind a `Protocol` port in `application/ports.py`, with a fake in `tests/fakes/`.
- Wire dependencies only in `src/offline_rag/bootstrap.py`.
- Use the spec's ubiquitous language: `Layer`, `Node`, `KnowledgeItem`, `Issue`, `Executor`, `TransferPackage`, `RFP`, `Proposal`, `Rubric`. Don't invent synonyms.

## Tests
- `tests/unit`, `tests/integration`, `tests/smoke`, `tests/regression`, `tests/e2e`.
- Every change ships with tests. Before saying work is done, run:
  `uv run ruff check . && uv run mypy && uv run lint-imports && uv run pytest tests/unit`

## Decisions
- Record significant design decisions as ADRs in `docs/adr/` (use the `adr` skill).
