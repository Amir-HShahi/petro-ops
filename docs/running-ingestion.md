# Running knowledge ingestion

How to run the ingestion pipeline on one machine: Postgres, RabbitMQ, the outbox relay, the workers and the API. The design is in ADR 0005 (workers and outbox), ADR 0006 (API and CLI), ADR 0007 (Docling) and ADR 0008 (the live pipeline page). Every service listens on `127.0.0.1` only.

## Quick start

Once per machine (details in [One-time setup](#one-time-setup)):

```bash
uv sync
cp .env.example .env
uv run docling-tools models download layout tableformer -o models/docling
ollama pull gemma4:12b-it-qat && ollama pull glm-ocr:latest   # scanned PDFs only
```

Every time:

```bash
docker/pipeline-up.sh
```

Open <http://127.0.0.1:8000/pipeline>, pick a file and a Node, and submit. Press Ctrl+C to stop; Postgres and RabbitMQ keep running. Add `--no-vision` when Ollama is off, `--text-workers 0` for the demo below, and `--down` to stop the containers too. Logs are in `data/logs/`.

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
docker compose -f docker/docker-compose.yml up -d --wait postgres rabbitmq
docker compose -f docker/docker-compose.yml run --rm rabbitmq-policies
```

This starts Postgres on `127.0.0.1:55432` and RabbitMQ on `127.0.0.1:5672`, with its management UI and API on `http://127.0.0.1:15672`. The pipeline page reads its queue counts from that API, refreshed every second. The one-shot `rabbitmq-policies` service gives the vision queue a 6 h consumer timeout: a long scanned report takes longer than the 30 min default, and RabbitMQ 4 accepts this only as a policy (ADR 0005). Check it with:

```bash
docker compose -f docker/docker-compose.yml exec rabbitmq rabbitmqctl list_policies
```

Stop everything with `docker compose -f docker/docker-compose.yml down`; add `-v` to delete the data too.

Create the tables:

```bash
uv run alembic upgrade head
```

## Start everything with one command

```bash
docker/pipeline-up.sh
```

It starts Postgres and RabbitMQ, applies the vision-queue policy, creates the tables, then starts the relay, one text worker, the vision worker and the API. It prints the pipeline page URL, and each process logs to `data/logs/<name>.log`. Ctrl+C stops the processes; the containers keep running.

| Option | Effect |
|---|---|
| `--text-workers N` | Start N text workers (default 1). `0` lets the queue fill until you start one by hand. |
| `--no-vision` | Skip the vision worker, for example when Ollama is not running. |
| `--no-docker` | Use the Postgres and RabbitMQ already running at `DATABASE_URL` and `RABBITMQ_URL`. |
| `--down` | Also stop the containers on exit. Their data is kept. |

It refuses to start while another relay, worker or API runs, since only one relay may run (ADR 0005). If one of its processes dies, it shows the last lines of that log and stops the rest.

## Start the pipeline by hand

Run each in its own terminal and stop them with Ctrl+C. A worker acks a message only after its step is saved, so a message it was still working on goes back to the queue.

```bash
uv run knowledge relay run
uv run knowledge worker run --lane text
uv run knowledge worker run --lane vision   # needs Ollama running
uv run knowledge api run                    # http://127.0.0.1:8000, docs at /docs
```

Log lines are JSON on stderr.

## Watch it live

Open <http://127.0.0.1:8000/pipeline> while the API runs. The page needs no internet. It shows:

- a form to submit a file for a registered Node;
- the outbox and the four queues (`ingestion`, `ingestion.vision`, `ingestion.retry`, `ingestion.dlq`), each with messages waiting (blue squares), messages a worker holds and has not acked (amber squares) and consumers;
- the 20 most recent ingestions as cards in the column of their status. Click a completed card to see its blocks, with the page or heading path, table or text, and the review flag.

The page polls every second. If RabbitMQ's management API is down, the queue panel shows `KNOWLEDGE_QUEUE_MONITOR_UNAVAILABLE` and the cards keep updating.

## Two-minute demo

Before the demo: Ollama runs with both vision models (for step 3), and the queues are empty. Start everything except the text worker, then open the page:

```bash
docker/pipeline-up.sh --text-workers 0        # terminal 1
# terminal 2: the text worker, started in step 2
```

Make a broken file for step 4. It starts like a DOCX, so the submit accepts it, but it cannot be read:

```bash
printf 'PK\003\004this is not a real docx' > /tmp/broken_report.docx
```

1. **Queue fills (30 s).** No text worker runs yet; `ingestion` shows 0 consumers. Submit these three from the page, Node `sp12_inspection_team`:
   - `fixtures/docs/synthetic/inspection_sp12_riser_r3_2024.docx` (`inspection_report`)
   - `fixtures/docs/synthetic/shift_report_sp12_2026_08_04.docx` (`shift_report`)
   - `fixtures/docs/synthetic/project_report_sp12_riser_r3_integrity.pdf` (`project_report`)

   Each card appears under Queued. The outbox count goes up, then the relay moves each message to `ingestion`, which shows 3 waiting. Point out that the files are safe in Postgres and the broker even though no worker runs.
2. **Queue drains (30 s).** In terminal 2, run `uv run knowledge worker run --lane text`. `ingestion` shows 1 consumer and 1 in progress. The cards move to Extracting and then Completed one by one, and the queue drains to 0. Click a completed card to show its blocks: headings for the DOCX files, page numbers and tables for the PDF.
3. **Vision lane (about a minute per page).** Submit `fixtures/docs/cases/scanned_sp12_riser_r3_baseline_2021.pdf` (`inspection_report`). The text worker finds pages without a text layer, so the card moves Extracting → Reading pages and one message appears in `ingestion.vision`, held by its single consumer. When Gemma and `glm-ocr` are done, the card is Completed with its `blocks_for_review`. Click it: the blocks read by the LVM carry an LVM badge, and tables the two models read differently are flagged for review.
4. **A file that fails (10 s).** Submit `/tmp/broken_report.docx`. The card moves to Failed with `KNOWLEDGE_EXTRACTION_FAILED` after one attempt. A broken file is a domain error, so it is not retried and nothing lands in `ingestion.retry` or `ingestion.dlq`. A file in another format, such as a `.txt`, is refused by the form itself with `KNOWLEDGE_UNSUPPORTED_FORMAT` and never becomes a card.

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
  -e POSTGRES_PASSWORD=petro_ops -p 127.0.0.1:55433:5432 postgres:17.11-alpine
docker run -d --rm --name petro-ops-mq-test -e RABBITMQ_DEFAULT_USER=petro_ops \
  -e RABBITMQ_DEFAULT_PASS=petro_ops -p 127.0.0.1:55673:5672 -p 127.0.0.1:55674:15672 \
  rabbitmq:4.4.0-management-alpine

DATABASE_URL=postgresql://petro_ops:petro_ops@127.0.0.1:55433/petro_ops \
RABBITMQ_URL=amqp://petro_ops:petro_ops@127.0.0.1:55673/%2F \
RABBITMQ_MANAGEMENT_URL=http://petro_ops:petro_ops@127.0.0.1:55674 \
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
| `KNOWLEDGE_QUEUE_MONITOR_UNAVAILABLE` on the page | RabbitMQ is down or `RABBITMQ_MANAGEMENT_URL` is wrong. Ingestion still works. |
