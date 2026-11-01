---
paths:
  - "**/*.py"
---
# Python naming

Ruff enforces PEP 8 casing. These rules cover what it can't check.

## Modules

- Name a module after what it holds: `knowledge_item.py`, `ports.py`, `ingest_document.py`.
- No catch-all modules like `models.py`, `utils.py`, `helpers.py` or `common.py`.

## Domain

- Entities and value objects are plain nouns with no suffix: `KnowledgeItem`, `ChunkSpan`, not `KnowledgeItemEntity` or `ChunkSpanVO`.
- Domain errors end in `Error`: `DuplicateKnowledgeError`. Error classes are defined only in `errors.py` files.
- Domain events are in the past tense: `KnowledgeItemIngested`.

## Application

- Commands are imperative: `IngestDocument`.
- Handlers are `<Command>Handler`: `IngestDocumentHandler`.
- One use case per file, named after it: `ingest_document.py`.

## Ports, adapters and fakes

- Ports are named by role, with no `I` prefix or `Port` suffix: `Embedder`, `VectorStore`, `DocumentParser`, `KnowledgeRepository`.
- Adapters are technology plus role: `LlamaCppLLM`, `LanceDbVectorStore`, `DocxParser`, `SqliteKnowledgeRepository`.
- Fakes are `InMemory<Port>` or `Fake<Port>`: `InMemoryKnowledgeRepository`, `FakeEmbedder`.

## Methods

- Commands are verbs: `ingest`, `promote`, `transfer`.
- Queries are nouns or start with `get_` / `find_`. `get_` raises if nothing is found; `find_` returns `None`.

## Tests

- Test files are `test_<module>.py`.
- Test functions are `test_<behavior>_when_<condition>`.

## Private names

- Use a single leading underscore for internals: `_build_index`. Don't use `__name` mangling.
