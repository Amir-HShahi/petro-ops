# petro-ops

Offline hierarchical RAG core for organizational knowledge, issue management and knowledge transfer between layers. Runs fully offline on small local embedding, LLM and vision models.

## Setup

```bash
uv sync
uv run pre-commit install
```

Legacy DOC files are converted with LibreOffice, which must be installed on the machine:

```bash
brew install --cask libreoffice        # macOS
sudo apt install libreoffice-writer    # Debian or Ubuntu
```

Settings have working defaults. To change one, copy `.env.example` to `.env` and edit it there; every variable is explained in that file.

## Local models

The core uses local models through [Ollama](https://ollama.com) on the loopback address only; any other address is refused. The chosen models, their roles and digests are in `models/manifest.yaml`. The reasons and benchmark results are in `docs/adr/0001-local-models-and-runtime.md` and `docs/adr/0002-lvm-ocr-and-document-parsers.md`.

| Role | Model | Used for |
|---|---|---|
| LLM and LVM | `gemma4:12b-it-qat` | Answers, and reading scanned PDF pages |
| OCR | `glm-ocr:latest` | Reading every table on a scanned page a second time, to check the LVM |
| Embedding | `embeddinggemma:300m` | Retrieval and duplicate detection |

```bash
ollama pull gemma4:12b-it-qat
ollama pull glm-ocr:latest
ollama pull embeddinggemma:300m
ollama list   # the digests should match models/manifest.yaml
```

Start the server with `ollama serve`, or open the Ollama app. Model weights are never committed.

The core loads one large model at a time and unloads it when its work is done, because Gemma and `glm-ocr` together do not fit next to other apps on a 16 GB machine. Close heavy apps before reading many scanned pages.

## Ingesting documents

Submitting a file registers it and queues a KnowledgeIngestion; workers do the rest (ADR 0005):

1. **Register.** The format is read from the file's content (DOC, DOCX or PDF). The file is kept in `data/source_files/`, and the KnowledgeItem, its ingestion and the message that starts it are stored in Postgres in one transaction. The owning Node must be registered in Organizational Hierarchy; `uv run organization import-nodes` registers the case-study Nodes.
2. **Extract** (text worker). Docling reads the text and tables in order, with the page (PDF) or heading path (DOC, DOCX) of each block. DOC files are converted by LibreOffice first.
3. **Read pages** (vision worker). PDF pages without a text layer are read by Gemma, and every table on them is checked against `glm-ocr`. A table the two models read differently is marked for human review. This takes about a minute per page.

```bash
uv run knowledge submit fixtures/docs/synthetic/inspection_sp12_riser_r3_2024.docx --node sp12_inspection_team
uv run knowledge status <ingestion_id>
uv run knowledge show-content <item_id> --limit 20
```

Postgres and RabbitMQ run in Docker: `docker compose -f docker/docker-compose.yml up -d`. The same actions are available over HTTP with `uv run knowledge api run`, which also serves a live view of the pipeline at <http://127.0.0.1:8000/pipeline>. `docker/pipeline-up.sh` starts all of it with one command. See the [quick start](docs/running-ingestion.md#quick-start); the same file covers the options, the demo script and starting each part by hand.

Each command prints its result to stdout as JSON. Errors go to stderr as [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) Problem Details with a code from `docs/errors.md`, and log lines go to stderr as JSON. Set `LOG_LEVEL=debug` to see every step. Add `--help` to any command for all its options.

## Organizational hierarchy

The Layers, the Nodes in them and what each Layer requires of the packages it receives (spec §6, §10.1). The five Layers are created by the migrations; the case-study Nodes come from `fixtures/registry/nodes.csv`.

```bash
uv run organization import-nodes
uv run organization register-node sp12_ndt_team --name "SP-12 NDT Team" --layer 3 --parent platform_sp12 --activity-area "non-destructive testing" --reporting-rule weekly
uv run organization define-transfer-rule 1 --detail-level managerial --required-topic "key risks" --output-format markdown --max-package-length-tokens 1500 --source-reference-level document
```

`docker/organization-demo.sh` runs the whole flow step by step: it starts Postgres, creates the tables, imports the chart, registers a Node, shows the hierarchy rules refusing four bad Nodes, defines the transfer rules of Layers 0 to 3 and prints the chart. Add `--reset` to start from an empty chart.

## Issues

An Issue is a problem a Node works on, split into a tree of SubIssues (spec §12). An Issue can only be raised for a registered Node, so import the Nodes first. A new Issue is compared with the Node's other Issues, and any that look like it are listed under `similar_issues` as a likely `duplicate` or an `overlap` (ADR 0012). Both Issues are kept.

```bash
uv run issue raise --node platform_sp12 --title "Riser R-3 splash zone corrosion" --description "Gas export riser R-3 is losing wall in the splash zone." --domain "asset integrity" --tag riser
uv run issue add-sub-issue <issue_id> --title "Permanent repair option" --description "Choose between a clamp-on sleeve and a section replacement."
uv run issue add-sub-issue <issue_id> --parent <sub_issue_id> --title "Clamp-on sleeve" --description "Check whether a sleeve can carry the riser loads."
uv run issue show <issue_id>
uv run issue list --node platform_sp12
```

`add-sub-issue` prints the new id as `added_sub_issue_id`. Pass it as `--parent` to split that SubIssue further; a new SubIssue goes last among its siblings.

## Checks

```bash
uv run ruff check .
uv run mypy
uv run lint-imports
uv run pytest tests/unit
```

CI also runs the integration tests and checks coverage on both suites:

```bash
uv run pytest tests/unit tests/integration -m "not slow" --cov-fail-under=80
```

The integration tests need Postgres and RabbitMQ from `docker/docker-compose.yml`, and LibreOffice for the DOC tests; they skip when these are missing.

Tests marked `slow` run the real models on the scanned fixtures. They need Ollama with both models pulled, take about two minutes, and skip themselves when Ollama is not running:

```bash
uv run pytest tests/integration -m slow -v --no-cov
```

## Layout

- `src/offline_rag/<context>/` — one bounded context, split into `domain`, `application`, `infrastructure`, `interface`
- `src/offline_rag/bootstrap.py` — wires ports to adapters
- `tests/` — `unit`, `integration`, `smoke`, `regression`, `e2e`, and the in-memory fakes in `fakes/`
- `prompts/` — versioned prompt templates and `registry.yaml`
- `models/manifest.yaml` — the local model of each role
- `fixtures/` — sample documents, the Node registry and the golden set
- `docs/` — the spec, the error contract and the ADRs in `adr/`
- `data/` — the local database and stored files, created on first use and never committed

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branching, commit and PR flow.
