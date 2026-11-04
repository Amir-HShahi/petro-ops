# 0006. Ingestion API and CLI

Date: 2026-11-04
Status: Proposed

## Context
Users submit files and follow ingestion from a terminal, and a later UI needs the same actions over HTTP. The two must not drift apart.

## Decision
- **One application service** holds the logic. The CLI and a FastAPI app are thin interfaces over it.
- **API**, FastAPI, bound to the loopback address (`API_HOST`, `API_PORT`), ingestion only:

  | Action | Route |
  |---|---|
  | Submit | `POST /knowledge-items` (multipart, returns 202 with `item_id`, `ingestion_id`, `status`) |
  | Status | `GET /knowledge-ingestions/{id}` |
  | Read content | `GET /knowledge-items/{id}/versions/{tag}/content` |
  | Run again | `POST /knowledge-items/{id}/versions/{tag}/ingestions` |
  | Health | `GET /health` |

- **CLI:** `knowledge submit FILE --node ID`, `knowledge status INGESTION_ID`, `knowledge show-content ITEM_ID [--version TAG]`, `knowledge reingest ITEM_ID [--version TAG]`, `knowledge worker run --lane text|vision`, `knowledge relay run`. Without `--version` the latest version is used.
- Errors use the existing Problem Details format. New codes go in `docs/errors.md`.
- Uploads larger than `MAX_FILE_MB` are refused.

## Alternatives
- **CLI only.** Simpler, but a UI would later need its own entry point.
- **Flask or a plain ASGI app.** FastAPI gives request validation and an OpenAPI schema with little code.
- **Synchronous submit that waits for extraction.** Scanned files take minutes, so the request would time out.

## Consequences
- FastAPI and an ASGI server become dependencies.
- The API has no authentication; the loopback binding is its only guard. Serving other machines needs a new ADR.
- RAG query routes are out of scope and come with phase 8.
