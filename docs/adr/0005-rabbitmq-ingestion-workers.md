# 0005. RabbitMQ workers, outbox and loopback-only services

Date: 2026-11-04
Status: Proposed

## Context
Ingesting a KnowledgeItem is slow: Docling extraction takes seconds, and each scanned page takes about 24 s for Gemma plus 13 s for `glm-ocr` (ADR 0002). Submitting a file must return at once, a crash must not lose work, and only one vision model may be in memory at a time. The project is fully offline, but Postgres, RabbitMQ and the API are sockets.

## Decision
- **One pipeline:** `KnowledgeIngestion` replaces the three event-chained use cases. Its status moves `QUEUED → EXTRACTING → (READING_PAGES) → COMPLETED`, and to `FAILED` from any running state.
- **Broker:** RabbitMQ. Direct exchange `ingestion.x` with keys `text` and `vision`. Queue `ingestion` has N text workers; `ingestion.vision` has one consumer, so one model is loaded at a time. `ingestion.retry` holds messages for `WORKER_RETRY_DELAY_S` and dead-letters them back to `ingestion.x` with the same key. Workers send to it through the fanout exchange `ingestion.retry.x`, so a message keeps its own key; the delay is a per-message expiry, so changing the setting needs no queue redeclare. An `attempt` header counts tries. `ingestion.dlq` keeps messages that failed `WORKER_MAX_ATTEMPTS` times, and malformed ones, with their lane and reason in headers.
- Durable queues, persistent messages, publisher confirms, manual ack, prefetch `WORKER_PREFETCH_COUNT` (1). A broker policy sets `consumer-timeout` on `ingestion.vision` to 6 h, since a long scanned report outlasts the 30 min default. It is a policy because RabbitMQ 4 refuses `x-consumer-timeout` as a queue or consumer argument on classic queues; the compose setup applies it.
- **One worker per step:** a worker starts a step only if the stored status is still the one it read (a row lock in Postgres). A fresh message starts only a `QUEUED` run; a redelivered or retried one may also restart an `EXTRACTING` run.
- **Transactional outbox:** the item, its `knowledge_ingestion` row and an `outbox_message` row commit in one transaction. A relay publishes unsent rows oldest first and marks each one sent once the broker has it; unsent rows wait for its next pass. Run one relay at a time. A reconciler catches messages lost after publishing (broker data loss, a purged queue): an ingestion that is `QUEUED` or `READING_PAGES`, has all its messages sent and has not changed for `RECONCILE_AFTER_S` gets a new outbox row. It skips `EXTRACTING` runs, because the broker redelivers their unacked message.
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
