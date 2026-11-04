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

A file goes through three steps, one after the other, when it is submitted:

1. **Register.** The format is read from the file's content (DOC, DOCX or PDF). The file is kept in `data/source_files/` and a KnowledgeItem with its first version is stored in `data/knowledge.sqlite3`. The owning Node must be in `fixtures/registry/nodes.csv`.
2. **Extract.** The text and tables are read in order, with the page (PDF) or heading path (DOC, DOCX) of each block.
3. **LVM assist.** PDF pages without a text layer are read by Gemma, and every table on them is checked against `glm-ocr`. A table the two models read differently is marked for human review. This takes about a minute per page.

If Extract or LVM assist fails, for example because LibreOffice or Ollama is missing, the item stays registered and the step can be run again later.

Run the commands from the repository root:

```bash
# Register a file; Extract and LVM assist run right after it
uv run python -m offline_rag.knowledge.interface.cli submit fixtures/docs/cases/scanned_sp12_riser_r3_baseline_2021.pdf --node sp12_inspection_team --document-type inspection_report

# Print the extracted blocks of a version
uv run python -m offline_rag.knowledge.interface.cli show-content <item_id> --limit 20

# Run a step again for a version
uv run python -m offline_rag.knowledge.interface.cli extract <item_id> --version-tag v1
uv run python -m offline_rag.knowledge.interface.cli read-pages <item_id> --page 3
```

Each command prints its result to stdout as JSON. Errors go to stderr as [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) Problem Details with a code from `docs/errors.md`, and log lines go to stderr as JSON. Set `LOG_LEVEL=debug` to see every step. Add `--help` to any command for all its options.

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
