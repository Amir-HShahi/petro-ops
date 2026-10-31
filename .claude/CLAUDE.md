# Offline Hierarchical RAG Core

Source of truth for scope and domain terms: `../project-fa.md`.

## Stack
- Python 3.12, `uv`, `ruff`, `mypy --strict`, `pytest`, `import-linter`.
- Fully offline: never add cloud SDKs, API calls, or network access at runtime or in tests.

## Architecture (DDD + hexagonal)
- Code lives in `src/offline_rag/<bounded_context>/` with layers: `domain/` → `application/` → `infrastructure/` → `interface/`.
- `domain/` has no I/O and no third-party imports.
- Every model, store, or parser sits behind a `Protocol` port in `application/ports.py`, with a fake in `tests/fakes/`.
- Wire dependencies only in `src/offline_rag/bootstrap.py`.
- Use the spec's ubiquitous language: `Layer`, `Node`, `KnowledgeItem`, `Issue`, `Executor`, `TransferPackage`, `RFP`, `Proposal`, `Rubric`. Don't invent synonyms.

## Tests
- `tests/unit`, `tests/integration`, `tests/smoke`, `tests/regression`, `tests/e2e`.
- Every change ships with tests. Before saying work is done, run:
  `uv run ruff check . && uv run mypy src && uv run lint-imports && uv run pytest tests/unit`

## Decisions
- Record significant design decisions as ADRs in `docs/adr/` (use the `adr` skill).
