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
| `ORGANIZATION_INVALID_LAYER_INDEX` | Domain | A Layer index is not a whole number from 0 to 4. | Use a Layer from 0 (strategic) to 4 (knowledge sources). |
| `ORGANIZATION_INVALID_LAYER_DETAIL_LEVEL` | Domain | Layer 4 was given a detail level, or Layers 0 to 3 were given none. | Leave the detail level empty for Layer 4 and set one for every other Layer. |
| `ORGANIZATION_PARENT_NODE_REQUIRED` | Domain | A Node below Layer 0 has no parent Node. | Give the parent Node it reports to. |
| `ORGANIZATION_TOP_LAYER_NODE_HAS_PARENT` | Domain | A Layer 0 Node was given a parent, but Layer 0 is the top. | Remove the parent, or put the Node in a lower Layer. |
| `ORGANIZATION_PARENT_NOT_IN_HIGHER_LAYER` | Domain | A parent Node is in the same Layer as its child or a lower one. | Pick a parent in a higher Layer (a lower number). |
| `ORGANIZATION_PARENT_STRUCTURE_NOT_TRACKED` | Domain | A Node was placed under a parent whose internal structure is not tracked, so it cannot have children. | Turn on tracking for the parent, or pick another parent. |
| `KNOWLEDGE_EMPTY_FILE` | Domain | A submitted file has no content. | Submit the file again with its content. |
| `KNOWLEDGE_UNSUPPORTED_FORMAT` | Domain | A submitted file is not DOC, DOCX or PDF. The format is read from the file content, not its name. | Convert the file to DOC, DOCX or PDF. |
| `KNOWLEDGE_INVALID_VERSION_HISTORY` | Unexpected | A KnowledgeItem was built with versions that break the version rules. This is a bug or corrupted storage. | Report it with the `request_id`. |
| `KNOWLEDGE_FILE_TOO_LARGE` | Domain | A submitted file is larger than `MAX_FILE_MB`. | Split the file or compress its images, then submit it again. |
| `KNOWLEDGE_REQUEST_INVALID` | Domain | An API request is missing a field or has a field of the wrong type. `details.problems` lists each field and what is wrong with it. | Fix the listed fields and send the request again. |
| `KNOWLEDGE_OWNER_NODE_NOT_FOUND` | Not found | Knowledge was submitted for a Node that is not registered. | Register the Node first, or use the id of a registered Node. |
| `KNOWLEDGE_ITEM_NOT_FOUND` | Not found | No KnowledgeItem has the requested id. | Check the id. |
| `KNOWLEDGE_SOURCE_FILE_NOT_READABLE` | Not found | The file named in the command does not exist or cannot be read. | Check the path and the file's permissions. |
| `KNOWLEDGE_STORAGE_FAILED` | Infrastructure | The local knowledge database cannot be read or written, or a new item's id is already taken. | Check that `DATA_DIR` is writable and has free space, then try again. |
| `KNOWLEDGE_SOURCE_FILE_STORAGE_FAILED` | Infrastructure | A submitted file cannot be written to the local file store. | Check that `DATA_DIR` is writable and has free space, then try again. |
| `KNOWLEDGE_NODE_REGISTRY_UNAVAILABLE` | Infrastructure | The Node registry file is missing, has no `node_id` column or lists an invalid Node id. | Check `NODE_REGISTRY_PATH` and the file's content. |
| `KNOWLEDGE_VERSION_NOT_FOUND` | Not found | A KnowledgeItem has no version with the requested tag. | Check the version tag, such as `v1`. |
| `KNOWLEDGE_VERSION_CHANGE_REASON_MISSING` | Domain | A new version was published without a change reason. Every update must say why it was made (spec §7.6). | Send a short `change_reason`, then publish again. |
| `KNOWLEDGE_VERSION_UNCHANGED` | Domain | The file published as a new version is byte for byte the item's active version, so nothing changed. | Publish the changed file, or keep the active version. |
| `KNOWLEDGE_EXTRACTED_CONTENT_NOT_FOUND` | Not found | Nothing has been extracted from the requested version yet, or its extraction failed. | Run the extraction for that version. |
| `KNOWLEDGE_EXTRACTION_FAILED` | Domain | A file could not be read as the format its content claims. It may be damaged, password protected or another file type. | Open and save the file again, then submit it again. |
| `KNOWLEDGE_DOC_CONVERTER_UNAVAILABLE` | Infrastructure | A DOC file needs LibreOffice to be converted, and it is missing or did not finish in time. | Install LibreOffice or set `LIBREOFFICE_PATH`, then run the extraction again. |
| `KNOWLEDGE_PARSER_MODELS_UNAVAILABLE` | Infrastructure | Docling's layout or table-structure models are not in `DOCLING_MODELS_DIR`, so a PDF cannot be read. | Download them with `docling-tools models download layout tableformer -o <DOCLING_MODELS_DIR>`, then run the ingestion again. |
| `KNOWLEDGE_INVALID_EXTRACTED_CONTENT` | Unexpected | A parser returned content that breaks the extraction rules. This is a bug in a parser. | Report it with the `request_id`. |
| `KNOWLEDGE_MODEL_UNAVAILABLE` | Infrastructure | A local model did not answer: Ollama is not running, the model is not pulled, or the request timed out. | Start Ollama, pull the model in `models/manifest.yaml`, then run the step again. |
| `KNOWLEDGE_MODEL_OUTPUT_INVALID` | Infrastructure | A local model kept answering in a shape its output schema does not allow. | Try again. If it keeps failing, report it with the `request_id`. |
| `KNOWLEDGE_MODEL_URL_NOT_LOCAL` | Infrastructure | `OLLAMA_URL` points off this machine, which the offline rule forbids. | Set `OLLAMA_URL` to a loopback address such as `http://127.0.0.1:11434`. |
| `KNOWLEDGE_MODEL_REGISTRY_UNAVAILABLE` | Infrastructure | The prompt or model of a task cannot be loaded from `prompts/registry.yaml` or `models/manifest.yaml`. | Check both files, and that the core runs from the repository root or `PROMPTS_DIR` and `MODEL_MANIFEST_PATH` are set. |
| `KNOWLEDGE_INGESTION_NOT_FOUND` | Not found | No ingestion has the requested id. | Check the id returned when the file was submitted. |
| `KNOWLEDGE_INGESTION_ALREADY_RUNNING` | Domain | A version was sent for ingestion again while an earlier run has not ended. | Wait until the earlier run is `completed` or `failed`, then try again. |
| `KNOWLEDGE_INGESTION_STATUS_CHANGED` | Domain | Two workers tried to start the same ingestion step at once; the second one stopped and changed nothing. Workers handle it themselves. | Nothing; the first worker carries on. |
| `KNOWLEDGE_INGESTION_INVALID_TRANSITION` | Unexpected | An ingestion was asked to move to a status its current status does not allow. This is a bug. | Report it with the `request_id`. |
| `KNOWLEDGE_MESSAGE_BROKER_UNAVAILABLE` | Infrastructure | The local RabbitMQ broker cannot be reached or did not confirm a message. The message stays in the outbox and is sent later. | Start RabbitMQ and check `RABBITMQ_URL`. |
| `KNOWLEDGE_QUEUE_MONITOR_UNAVAILABLE` | Infrastructure | The queue counts cannot be read from RabbitMQ's management API: the broker is down, runs without the management plugin, or refuses the user in `RABBITMQ_MANAGEMENT_URL`. Ingestion itself is not affected. | Start RabbitMQ from `docker/docker-compose.yml` and check `RABBITMQ_MANAGEMENT_URL`. |
| `UNEXPECTED_ERROR` | Unexpected | A failure that is not a project error reached the edge. This is a bug. | Report it with the `request_id`. |
