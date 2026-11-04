# 0003. Local storage for knowledge items and source files

Date: 2026-11-04
Status: Proposed

## Context
Phase 4 registers DOC, DOCX and PDF files as KnowledgeItems (spec §7.2, §21 phase 4). Spec §17 asks for a local database for entities, metadata and version history, and file storage for the original documents. Everything must run offline on one machine, on both development machines in ADR 0001.

The Organizational Hierarchy context has no code yet (phase 6), but registration must check that the owning Node exists.

## Decision
- **KnowledgeItems:** a local SQLite file, `DATA_DIR/knowledge.sqlite3`, through `SqliteKnowledgeItemRepository`. One table holds the items and one holds their versions. Metadata is stored as JSON. An item and all its versions are written in one transaction.
- **Original files:** a local folder, `DATA_DIR/source_files/`, through `LocalSourceFileStore`. Each file gets a random name that keeps only a short suffix such as `.pdf`. The submitted name is kept in the version row, never used as a path.
- **Node registry:** `CsvNodeDirectory` reads the `node_id` column of `NODE_REGISTRY_PATH` (default `fixtures/registry/nodes.csv`) until Organizational Hierarchy has its own store.
- **Events:** delivered in the same process right after the save (`InProcessEventPublisher`), the default of AOQ 3 in `docs/application-services.md`.
- **Logging:** `structlog`, JSON lines to stderr, configured once in `bootstrap.py`.
- `DATA_DIR` is gitignored, because it holds real organizational data.

## Alternatives
- **Only in-memory fakes for now.** Simpler, but nothing survives a restart, so phase 4 could not be shown working.
- **PostgreSQL or another server database.** It needs a running service on every machine. SQLite is part of Python and needs nothing else.
- **Storing files inside SQLite as blobs.** One file to copy, but the database grows with every document, and large PDFs make backups and reads slow.
- **An outbox table for events.** It survives a crash between save and publish, but nothing consumes the events yet.

## Consequences
- Data survives restarts, and a copy of `DATA_DIR` is a full backup.
- The file is saved before the item. If the item cannot be saved, the file stays in the folder without an item. A clean-up job can remove such files later.
- An event is lost if the process stops between the save and the publish. This matters once later phases react to events, and then the outbox should be reconsidered.
- SQLite allows one writer at a time. That fits one user per machine, not many parallel workers.
- The schema is created on start. A change to it later needs a migration.
- The vector index for retrieval is a separate decision (phase 8).
