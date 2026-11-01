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
