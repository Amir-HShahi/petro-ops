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

- **CLI:** `knowledge submit FILE --node ID`, `knowledge status INGESTION_ID`, `knowledge show-content ITEM_ID [--version TAG]`, `knowledge reingest ITEM_ID [--version TAG]`, `knowledge worker run --lane text|vision`, `knowledge relay run`, `knowledge api run`. Without `--version` the active version is used, the one RAG serves; it can differ from the newest once versions can be rolled back.
- **Shared logic:** the CLI and the API call the same use case handlers and queries, and build their JSON bodies with the same functions, so both return the same fields.
- Errors use the existing Problem Details format. New codes go in `docs/errors.md`. The API reuses a caller's `X-Request-ID` and creates one only when it is missing.
- Files larger than `MAX_FILE_MB` are refused by the submit use case, for the CLI and the API alike (`KNOWLEDGE_FILE_TOO_LARGE`, 422). The API stops reading an upload just past the limit.

## Alternatives
- **CLI only.** Simpler, but a UI would later need its own entry point.
- **Flask or a plain ASGI app.** FastAPI gives request validation and an OpenAPI schema with little code.
- **Synchronous submit that waits for extraction.** Scanned files take minutes, so the request would time out.

## Consequences
- FastAPI and an ASGI server become dependencies.
- The API has no authentication; the loopback binding is its only guard. Serving other machines needs a new ADR.
- RAG query routes are out of scope and come with phase 8.
