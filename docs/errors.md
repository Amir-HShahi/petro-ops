# Errors

This is the error contract for the Python core, the Spring Boot backend and the Next.js frontend. All three follow it.

## Codes

- Every error has a code in `CONTEXT_REASON` form, upper snake case, for example `KNOWLEDGE_DUPLICATE`.
- `CONTEXT` is the bounded context. `REASON` says what went wrong.
- Codes are unique across the project. Once released, a code is never renamed or reused.
- Clients decide what to do based on the code, never on the message text.

## Categories

Each error belongs to one category. The category decides the HTTP status.

| Category | Meaning | HTTP status |
|---|---|---|
| Domain | A business rule was broken by the request | 400, 409 or 422 |
| Not found | The requested item doesn't exist | 404 |
| Infrastructure | A model, database, file or other dependency failed | 503 |
| Unexpected | Anything not covered above, which is a bug | 500 |

New categories need an ADR.

## Response format

APIs return errors as [RFC 9457 Problem Details](https://www.rfc-editor.org/rfc/rfc9457), with `Content-Type: application/problem+json`.

```json
{
  "type": "KNOWLEDGE_DUPLICATE",
  "title": "Duplicate knowledge item",
  "status": 409,
  "detail": "KnowledgeItem 'a17' duplicates 'b42' in node 'N7'.",
  "request_id": "3f9c1e2a",
  "details": { "item_id": "a17", "duplicate_of": "b42", "node_id": "N7" }
}
```

- `type` is the error code.
- `detail` is the message saying what is wrong. The frontend shows it as is.
- `details` holds structured values. Its fields are part of the contract for that code.
- Responses never contain stack traces, file paths or internal library errors.

## Request ID

- The frontend creates a request ID for each user action and sends it as the `X-Request-ID` header.
- The backend forwards the same header to the core. If a request arrives without one, the first service creates it.
- Every service puts the request ID in its logs and in error responses.
- The frontend may show it to users as an error reference, so a report can be traced through all three services.

## Frontend

- The frontend shows the code and the message it receives. It doesn't map codes to its own text.

## Catalog

Add a row in the same PR that adds the code.

| Code | Category | Meaning | How to fix |
|---|---|---|---|
| `ORGANIZATION_INVALID_NODE_IDENTIFIER` | Domain | A Node id is empty or starts or ends with a space. | Send the Node id exactly as it is in the registry. |
| `KNOWLEDGE_EMPTY_FILE` | Domain | A submitted file has no content. | Submit the file again with its content. |
| `KNOWLEDGE_UNSUPPORTED_FORMAT` | Domain | A submitted file is not DOC, DOCX or PDF. The format is read from the file content, not its name. | Convert the file to DOC, DOCX or PDF. |
| `KNOWLEDGE_INVALID_VERSION_HISTORY` | Unexpected | A KnowledgeItem was built with versions that break the version rules. This is a bug or corrupted storage. | Report it with the `request_id`. |
| `KNOWLEDGE_OWNER_NODE_NOT_FOUND` | Not found | Knowledge was submitted for a Node that is not registered. | Register the Node first, or use the id of a registered Node. |
| `KNOWLEDGE_ITEM_NOT_FOUND` | Not found | No KnowledgeItem has the requested id. | Check the id. |
| `KNOWLEDGE_SOURCE_FILE_NOT_READABLE` | Not found | The file named in the command does not exist or cannot be read. | Check the path and the file's permissions. |
| `KNOWLEDGE_STORAGE_FAILED` | Infrastructure | The local knowledge database cannot be read or written, or a new item's id is already taken. | Check that `DATA_DIR` is writable and has free space, then try again. |
| `KNOWLEDGE_SOURCE_FILE_STORAGE_FAILED` | Infrastructure | A submitted file cannot be written to the local file store. | Check that `DATA_DIR` is writable and has free space, then try again. |
| `KNOWLEDGE_NODE_REGISTRY_UNAVAILABLE` | Infrastructure | The Node registry file is missing, has no `node_id` column or lists an invalid Node id. | Check `NODE_REGISTRY_PATH` and the file's content. |
| `KNOWLEDGE_VERSION_NOT_FOUND` | Not found | A KnowledgeItem has no version with the requested tag. | Check the version tag, such as `v1`. |
| `KNOWLEDGE_EXTRACTED_CONTENT_NOT_FOUND` | Not found | Nothing has been extracted from the requested version yet, or its extraction failed. | Run the extraction for that version. |
| `KNOWLEDGE_EXTRACTION_FAILED` | Domain | A file could not be read as the format its content claims. It may be damaged, password protected or another file type. | Open and save the file again, then submit it again. |
| `KNOWLEDGE_DOC_CONVERTER_UNAVAILABLE` | Infrastructure | A DOC file needs LibreOffice to be converted, and it is missing or did not finish in time. | Install LibreOffice or set `LIBREOFFICE_PATH`, then run the extraction again. |
| `KNOWLEDGE_INVALID_EXTRACTED_CONTENT` | Unexpected | A parser returned content that breaks the extraction rules. This is a bug in a parser. | Report it with the `request_id`. |
| `KNOWLEDGE_MODEL_UNAVAILABLE` | Infrastructure | A local model did not answer: Ollama is not running, the model is not pulled, or the request timed out. | Start Ollama, pull the model in `models/manifest.yaml`, then run the step again. |
| `KNOWLEDGE_MODEL_OUTPUT_INVALID` | Infrastructure | A local model kept answering in a shape its output schema does not allow. | Try again. If it keeps failing, report it with the `request_id`. |
| `KNOWLEDGE_MODEL_URL_NOT_LOCAL` | Infrastructure | `OLLAMA_URL` points off this machine, which the offline rule forbids. | Set `OLLAMA_URL` to a loopback address such as `http://127.0.0.1:11434`. |
| `KNOWLEDGE_MODEL_REGISTRY_UNAVAILABLE` | Infrastructure | The prompt or model of a task cannot be loaded from `prompts/registry.yaml` or `models/manifest.yaml`. | Check both files, and that the core runs from the repository root or `PROMPTS_DIR` and `MODEL_MANIFEST_PATH` are set. |
| `UNEXPECTED_ERROR` | Unexpected | A failure that is not a project error reached the edge. This is a bug. | Report it with the `request_id`. |
