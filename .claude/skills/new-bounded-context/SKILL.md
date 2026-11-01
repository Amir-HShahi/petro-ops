---
name: new-bounded-context
description: Create a new DDD bounded context in src/offline_rag with its four layers, test folders and import-linter contract. Use when starting work on a context that has no code yet.
---

1. Check the name against the contexts in the project spec (`docs/project-fa.md`) or user prompt. Use the same or related name, in snake_case.
2. Add `__init__.py` to `src/offline_rag/<ctx>/` and to each layer: `domain/`, `application/`, `infrastructure/`, `interface/`.
3. Create `tests/unit/<ctx>/` and `tests/integration/<ctx>/`, each with an empty `__init__.py`.
4. Add the context to the layers contract in `pyproject.toml`. If the contract doesn't exist yet, create it:

   ```toml
   [[tool.importlinter.contracts]]
   name = "Hexagonal layers in each bounded context"
   type = "layers"
   containers = ["offline_rag.<ctx>"]
   layers = ["interface", "infrastructure", "application", "domain"]
   ```

5. Run `uv run lint-imports` and `uv run mypy` and fix anything that fails.

Don't create placeholder classes or example code. The context starts empty and grows through real use cases (see the `new-use-case` skill).
