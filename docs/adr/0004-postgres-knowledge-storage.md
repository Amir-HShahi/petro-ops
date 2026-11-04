# 0004. Postgres for knowledge data

Date: 2026-11-04
Status: Proposed

## Context
ADR 0003 stored KnowledgeItems in SQLite and delivered events in the same process. Ingestion now runs in several workers over a message broker (ADR 0005), so many processes write at once. SQLite allows one writer at a time, and an event is lost if the process stops between the save and the publish. Spec §17 asks for a local database for entities, metadata and version history. Everything must still run offline on one machine.

## Decision
- **Database:** PostgreSQL on the loopback address, for all knowledge data: `knowledge_item`, `knowledge_version`, `extracted_content_block`, `knowledge_ingestion` and `outbox_message`.
- **Driver:** psycopg 3, with a connection pool sized by `DATABASE_POOL_SIZE`.
- **Migrations:** Alembic. The schema is no longer created on start.
- **Original files:** unchanged from ADR 0003, in `DATA_DIR/source_files/`.
- This supersedes the storage and events parts of ADR 0003. Its file store, Node registry and logging decisions stay.

## Alternatives
- **Keep SQLite.** No service to run, but one writer at a time does not fit parallel workers.
- **SQLAlchemy ORM.** More abstraction than the few tables need; plain SQL through psycopg keeps the adapters short. Alembic still runs on SQLAlchemy Core.
- **Hand-written SQL migration scripts.** Fewer dependencies, but no history table or downgrade path.

## Consequences
- Many workers can write at once, and the outbox can share a transaction with the data (ADR 0005).
- Postgres must run on every machine and in CI. `docker/docker-compose.yml` provides it.
- Integration tests need a running Postgres and skip clearly when it is absent. SQLite tests no longer stand in for it.
- Every schema change ships as an Alembic migration.
