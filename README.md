# petro-ops

Offline hierarchical RAG core for organizational knowledge, issue management and knowledge transfer between layers. Runs fully offline on small local embedding, LLM and vision models.

## Setup

```bash
uv sync
uv run pre-commit install
```

## Checks

```bash
uv run ruff check .
uv run mypy
uv run lint-imports
uv run pytest tests/unit
```

## Layout

- `src/offline_rag/<context>/` — one bounded context, split into `domain`, `application`, `infrastructure`, `interface`
- `tests/` — `unit`, `integration`, `smoke`, `regression`, `e2e`
- `prompts/` — versioned prompt templates
- `docs/adr/` — architecture decision records

## Contributing

Trunk-based: short-lived branches off `master`, squash-merged through PRs. Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `chore:` ...).
