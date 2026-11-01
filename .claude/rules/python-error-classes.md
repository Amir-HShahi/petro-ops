---
paths:
  - "**/errors.py"
---
# Defining errors

The error contract shared with the backend and frontend is in `docs/errors.md`.

## Where errors live

- Base classes live in `src/offline_rag/shared_kernel/errors.py`.
- Each bounded context keeps its errors in `errors.py` inside the layer that raises them, usually `domain/errors.py`.
- Error classes are defined only in `errors.py` files.

## What every error must have

- It inherits from one of the base categories in the shared kernel, never directly from `Exception`.
- Its class name ends in `Error`.
- A `code` class attribute in `CONTEXT_REASON` form, upper snake case, unique across the project. Once released, a code is never renamed or reused.
- A clear message that says what is wrong and, when known, what to do about it. The frontend shows it as is, so it must make sense to a user and must not contain internals like stack traces, file paths or library errors.
- Structured `details` (IDs, limits, values) so nothing has to be parsed from the message.

## Categories

- Every error belongs to exactly one category. The category decides the HTTP status (see `docs/errors.md`).
- Add a new category only with an ADR.

## Catalog

- Every new code is added to the catalog in `docs/errors.md` in the same PR.
