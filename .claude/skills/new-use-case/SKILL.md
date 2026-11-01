---
name: new-use-case
description: Add an application use case (command + handler) to a bounded context, with its ports, fakes and unit tests. Use when implementing an action such as ingesting a document, creating an issue or building a transfer package.
---

1. Make sure the context exists. If it doesn't, run the `new-bounded-context` skill first.
2. Put the business rules in `domain/` first: entities, value objects and domain errors. The handler only coordinates.
3. Define the input as a frozen dataclass in `application/commands.py`.
4. Write the handler in `application/<use_case>.py`. It may depend on `domain/` and on ports, never on `infrastructure/`.
5. If the handler needs storage, a model or a parser, add a `Protocol` to `application/ports.py` and a matching in-memory fake in `tests/fakes/`.
6. Write the unit tests with the `write-tests` skill.
7. Once real adapters exist, wire the handler in `src/offline_rag/bootstrap.py`.
