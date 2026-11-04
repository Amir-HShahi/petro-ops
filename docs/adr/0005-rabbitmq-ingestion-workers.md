# 0005. RabbitMQ workers, outbox and loopback-only services

Date: 2026-11-04
Status: Proposed

## Context
Ingesting a KnowledgeItem is slow: Docling extraction takes seconds, and each scanned page takes about 24 s for Gemma plus 13 s for `glm-ocr` (ADR 0002). Submitting a file must return at once, a crash must not lose work, and only one vision model may be in memory at a time. The project is fully offline, but Postgres, RabbitMQ and the API are sockets.

## Decision
- **One pipeline:** `KnowledgeIngestion` replaces the three event-chained use cases. Its status moves `QUEUED → EXTRACTING → (READING_PAGES) → COMPLETED`, and to `FAILED` from any running state.
- **Broker:** RabbitMQ. Direct exchange `ingestion.x` with keys `text` and `vision`. Queue `ingestion` has N text workers; `ingestion.vision` has one consumer, so one model is loaded at a time. `ingestion.retry` holds messages for `WORKER_RETRY_DELAY_S` and dead-letters them back to `ingestion.x` with the same key. `ingestion.dlq` keeps messages that failed `WORKER_MAX_ATTEMPTS` times.
- Durable queues, persistent messages, manual ack, prefetch `WORKER_PREFETCH_COUNT` (1).
- **Transactional outbox:** the item, its `knowledge_ingestion` row and an `outbox_message` row commit in one transaction. A relay publishes unsent rows. A reconciler republishes rows still unsent after `RECONCILE_AFTER_S`.
- **Delivery:** at least once. Workers ack only after their save commits, and each step replaces its own output, so redelivery is safe. Domain errors (unsupported or empty file) set `FAILED` and ack without retry.
- **Network rule:** Ollama, Postgres, RabbitMQ and the API accept only loopback addresses. `Settings` rejects any other host, as it already does for Ollama.

## Alternatives
- **In-process events (ADR 0003).** No broker, but no parallel workers and events are lost on a crash.
- **A Postgres table as the queue (`SELECT … FOR UPDATE SKIP LOCKED`).** One less service, but retry delays, dead-lettering and separate lanes would be hand-written.
- **Celery or Dramatiq.** They hide the queue layout this design depends on (separate vision lane, retry via TTL).
- **Publishing straight after commit, no outbox.** A crash between commit and publish leaves an item `QUEUED` forever.

## Consequences
- Text extraction scales with workers; the vision lane stays serial on purpose.
- RabbitMQ must run on every machine and in CI.
- The broker's consumer timeout (30 min by default) must be raised for the vision queue, and long work must run off the connection thread so heartbeats continue.
- A message can arrive twice, so every step must stay idempotent.
- `CLAUDE.md` now says that runtime sockets are allowed only to loopback services.
