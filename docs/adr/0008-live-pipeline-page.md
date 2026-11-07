# 0008. Live pipeline page

Date: 2026-11-07
Status: Proposed

## Context
The ingestion pipeline (ADR 0005) is hard to see at work: a file passes through the outbox, RabbitMQ and two worker lanes, and the CLI shows one ingestion at a time. A teacher demo needs to show files moving through the stages and the queues filling and draining. The page must work fully offline, and the API stays ingestion only and bound to loopback (ADR 0006).

## Decision
- **Page:** `GET /pipeline`, served by the existing FastAPI app, with its CSS and JS under `/pipeline/assets`. Plain HTML, CSS and vanilla JS shipped in the package: no CDN, no npm, no web fonts. It polls the routes below about once a second.
- It shows an upload form (file, owner Node from the registry, document type) that calls `POST /knowledge-items`; each recent ingestion as a card in a column per status (`QUEUED → EXTRACTING → READING_PAGES → COMPLETED / FAILED`) with its file name, format, attempts, `blocks_for_review` and failure code; and the queues with their counts. A completed card opens its blocks through the existing content route.
- **New routes**, which extend the table in ADR 0006:

  | Action | Route |
  |---|---|
  | Recent ingestions | `GET /knowledge-ingestions?limit=20` (1 to 100, newest first, each with `source_file_name` and `document_format`) |
  | Queues | `GET /ingestion-queues` (`ingestion`, `ingestion.vision`, `ingestion.retry`, `ingestion.dlq`, each with `messages_ready`, `messages_unacked`, `consumers`; plus `unpublished_outbox_messages`) |
  | Nodes | `GET /nodes` (the registered Node ids, sorted) |
  | Page | `GET /pipeline`, `GET /pipeline/assets/…` |

- **Application:** `KnowledgeIngestionQueries` gains `list_recent_ingestions(limit)`, `get_queue_depths()`, `count_unpublished_messages()` and `list_node_ids()`. New ports and port methods: `KnowledgeIngestionRepository.find_recent(limit)` returning `KnowledgeIngestionSummary`, `Outbox.count_unpublished()`, `NodeDirectory.list_node_ids()` and `IngestionQueueMonitor.get_queue_depths()` returning `IngestionQueueDepth`.
- **Queue counts** come from RabbitMQ's management HTTP API, read by `RabbitMqManagementQueueMonitor` at `RABBITMQ_MANAGEMENT_URL` with the user and password in the URL. `Settings` accepts only loopback hosts, as for the other services (ADR 0005). A queue not declared yet counts as empty. If the API cannot be read, the route returns `KNOWLEDGE_QUEUE_MONITOR_UNAVAILABLE` (503) and the page keeps showing the ingestions.
- The compose broker and the CI service refresh the management counts every second (`collect_statistics_interval 1000`) instead of every 5 s, so the page follows a demo closely.

## Alternatives
- **AMQP passive `queue_declare`.** Needs no management plugin, but returns only waiting messages and consumers, not unacked ones, so a message a worker is working on would be invisible.
- **The RabbitMQ management UI.** Already there, but it shows neither ingestions nor the outbox, and switching windows breaks the demo.
- **Server-sent events or WebSockets.** Smoother, but statuses change in Postgres and counts are sampled by the broker, so a push channel would still poll on the server. One-second polling is simpler.
- **A frontend framework or a build step.** Not needed for one page, and it would add npm and a network install.

## Consequences
- The broker image must include the management plugin (`rabbitmq:4.4.0-management-alpine`), and its port is published on loopback.
- The API process now reads the management API, so a broker without the plugin breaks only the queue panel.
- The page has no authentication, like the rest of the API; the loopback binding is its only guard.
- Polling adds about two small requests a second per open page, each logged by the API. That is fine for one viewer and wasteful for many.
- The upcoming UI from ADR 0006 can reuse the three new routes.
