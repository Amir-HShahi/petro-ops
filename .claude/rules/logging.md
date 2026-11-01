---
paths:
  - "**/*.py"
---
# Logging

- Use `structlog` with JSON output. Configure it once, in `src/offline_rag/bootstrap.py`. Modules only call `structlog.get_logger()`.
- The domain layer doesn't log. Application and infrastructure layers do.
- Every log line carries `request_id`, and `node_id` where it applies. Calls to a model also carry the model name with its hash and the prompt id with its version.
- Log events as short snake_case names with fields, not sentences: `log.info("knowledge_item_ingested", item_id=..., chunks=12)`.
- Levels:
  - `debug`: internal detail useful when investigating.
  - `info`: something meaningful happened, such as an ingested document or a built transfer package.
  - `warning`: something went wrong but was recovered, such as a retry or fallback.
  - `error`: only at the edge, together with the exception.
- Never log document text, personal data, secrets, or full prompts and answers. Log IDs, counts and sizes instead.
