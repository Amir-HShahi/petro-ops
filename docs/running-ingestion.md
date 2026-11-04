# Running knowledge ingestion

How to run the ingestion pipeline on one machine: Postgres, RabbitMQ, the outbox relay, the workers and the API. The design is in ADR 0005 (workers and outbox), ADR 0006 (API and CLI) and ADR 0007 (Docling). Every service listens on `127.0.0.1` only.

## What runs

| Process | Command | How many |
|---|---|---|
| Postgres | `docker compose` | 1 |
| RabbitMQ | `docker compose` | 1 |
| Outbox relay | `uv run knowledge relay run` | exactly 1 |
| Text worker | `uv run knowledge worker run --lane text` | 1 or more |
| Vision worker | `uv run knowledge worker run --lane vision` | exactly 1 (one model in memory) |
| API | `uv run knowledge api run` | 1, optional |

`submit` stores the file and queues an ingestion. The relay sends it to a text worker, which extracts the text with Docling. If some PDF pages have no text layer, the vision worker reads them with Gemma and `glm-ocr`. Nothing is extracted until the relay and a text worker run.

## One-time setup

1. Install the system tools: Docker, LibreOffice (`soffice`, for DOC files) and [Ollama](https://ollama.com) (for scanned pages only).
2. Install the Python packages:

   ```bash
   uv sync
   ```

3. Create `.env` from the example and set the values for your machine:

   ```bash
   cp .env.example .env
   ```

4. Download Docling's layout and table models (a few hundred MB, once per machine):

   ```bash
   uv run docling-tools models download layout tableformer -o models/docling
   ```

   They are loaded only from `DOCLING_MODELS_DIR`; nothing is downloaded at run time.

5. Pull the vision models, needed only for scanned pages:

   ```bash
   ollama pull gemma4:12b-it-qat
   ollama pull glm-ocr:latest
   ```

## Start Postgres and RabbitMQ

```bash
docker compose -f docker/docker-compose.yml up -d --wait
```

This starts Postgres on `127.0.0.1:55432` and RabbitMQ on `127.0.0.1:5672`, with its management UI on `http://127.0.0.1:15672`. A one-shot `rabbitmq-policies` service then gives the vision queue a 6 h consumer timeout: a long scanned report takes longer than the 30 min default, and RabbitMQ 4 accepts this only as a policy (ADR 0005). Check it with:

```bash
docker compose -f docker/docker-compose.yml exec rabbitmq rabbitmqctl list_policies
```

Stop everything with `docker compose -f docker/docker-compose.yml down`; add `-v` to delete the data too.

Create the tables:

```bash
uv run alembic upgrade head
```

## Start the pipeline

Run each in its own terminal and stop them with Ctrl+C. A worker acks a message only after its step is saved, so a message it was still working on goes back to the queue.

```bash
uv run knowledge relay run
uv run knowledge worker run --lane text
uv run knowledge worker run --lane vision   # needs Ollama running
uv run knowledge api run                    # http://127.0.0.1:8000, docs at /docs
```

Log lines are JSON on stderr.

## Use it from the CLI

Results are JSON on stdout; errors are Problem Details on stderr (`docs/errors.md`).

```bash
uv run knowledge submit fixtures/docs/synthetic/inspection_sp12_riser_r3_2024.docx \
  --node sp12_inspection_team --document-type inspection_report --tag riser
# {"item_id": "...", "version_tag": "v1", "ingestion_id": "...", "status": "queued"}

uv run knowledge status INGESTION_ID
uv run knowledge show-content ITEM_ID --limit 5
uv run knowledge reingest ITEM_ID              # again, for example after a parser fix
```

`show-content` and `reingest` use the active version unless `--version TAG` is given.

## Use it over HTTP

```bash
curl -s -F file=@fixtures/docs/synthetic/project_report_sp12_riser_r3_integrity.pdf \
  -F node_id=sp12_inspection_team -F tags=riser \
  http://127.0.0.1:8000/knowledge-items

curl -s http://127.0.0.1:8000/knowledge-ingestions/INGESTION_ID
curl -s 'http://127.0.0.1:8000/knowledge-items/ITEM_ID/versions/v1/content?limit=5'
curl -s -X POST http://127.0.0.1:8000/knowledge-items/ITEM_ID/versions/v1/ingestions
curl -s http://127.0.0.1:8000/health
```

Send `X-Request-ID` to trace a request through the logs; the API makes one when it is missing.

## Run the tests

```bash
uv run ruff check . && uv run mypy && uv run lint-imports && uv run pytest tests/unit
```

Integration tests need Postgres and RabbitMQ. Use throwaway containers on other ports, so your data is not touched:

```bash
docker run -d --rm --name petro-ops-pg-test -e POSTGRES_USER=petro_ops \
  -e POSTGRES_PASSWORD=petro_ops -p 127.0.0.1:55433:5432 postgres:17-alpine
docker run -d --rm --name petro-ops-mq-test -e RABBITMQ_DEFAULT_USER=petro_ops \
  -e RABBITMQ_DEFAULT_PASS=petro_ops -p 127.0.0.1:55673:5672 rabbitmq:4-alpine

DATABASE_URL=postgresql://petro_ops:petro_ops@127.0.0.1:55433/petro_ops \
RABBITMQ_URL=amqp://petro_ops:petro_ops@127.0.0.1:55673/%2F \
uv run pytest tests/integration/knowledge -m "not slow" --no-cov

docker stop petro-ops-pg-test petro-ops-mq-test
```

Tests marked `slow` load real models: Docling for PDF files (skipped when `models/docling` is missing) and the Ollama vision models. Run them with `-m slow`.

## When something goes wrong

| Symptom | Likely cause |
|---|---|
| Status stays `queued` | The relay or the text workers are not running, or RabbitMQ is down. |
| `KNOWLEDGE_PARSER_MODELS_UNAVAILABLE` | Docling models are not in `DOCLING_MODELS_DIR`; see setup step 4. |
| `KNOWLEDGE_DOC_CONVERTER_UNAVAILABLE` | LibreOffice is missing; install it or set `LIBREOFFICE_PATH`. |
| Status stays `reading_pages` | The vision worker or Ollama is not running. |
| `failed` with `KNOWLEDGE_MODEL_UNAVAILABLE` | Ollama was down for every retry; start it, then `reingest`. |
| Messages in `ingestion.dlq` | A step failed `WORKER_MAX_ATTEMPTS` times; its `reason` header says why. |
