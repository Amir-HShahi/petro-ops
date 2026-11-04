"""The ingestion HTTP API, bound to a loopback address only (ADR 0006).

Start it with `knowledge api run`. Routes are thin: they call the same handlers
and queries as the CLI and return the same bodies. Errors are Problem Details.
"""

import re
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

import structlog
import uvicorn
from fastapi import FastAPI, File, Form, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from offline_rag.bootstrap import build_knowledge, configure_logging
from offline_rag.knowledge.application.commands import ReingestKnowledgeItem, SubmitKnowledgeItem
from offline_rag.knowledge.application.knowledge_ingestion_queries import (
    KnowledgeIngestionQueries,
)
from offline_rag.knowledge.application.reingest_knowledge_item import (
    ReingestKnowledgeItemHandler,
)
from offline_rag.knowledge.application.submit_knowledge_item import (
    BYTES_PER_MB,
    SubmitKnowledgeItemHandler,
)
from offline_rag.knowledge.domain.knowledge_scope import ConfidentialityLevel, KnowledgeScope
from offline_rag.knowledge.domain.version_tag import VersionTag
from offline_rag.knowledge.interface.errors import RequestInvalidError
from offline_rag.knowledge.interface.problem_details import (
    problem_for_unexpected_error,
    problem_from_error,
)
from offline_rag.knowledge.interface.response_bodies import (
    content_body,
    ingestion_body,
    receipt_body,
)
from offline_rag.settings import Settings
from offline_rag.shared_kernel.errors import ProjectError
from offline_rag.shared_kernel.metadata_record import MetadataRecord
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

log = structlog.get_logger()

PROBLEM_MEDIA_TYPE = "application/problem+json"
REQUEST_ID_HEADER = "X-Request-ID"
# A request id from a caller is reused only if it is this short and plain, so it
# cannot break log lines (docs/errors.md, "Request ID").
_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
ACCEPTED = 202


def create_app(
    *,
    submit_handler: SubmitKnowledgeItemHandler,
    reingest_handler: ReingestKnowledgeItemHandler,
    queries: KnowledgeIngestionQueries,
    max_file_mb: int,
    min_page_text_chars: int,
) -> FastAPI:
    """Return the API over the given use cases and queries.

    Args:
        submit_handler: Registers submitted files.
        reingest_handler: Queues a version again.
        queries: Reads ingestion status and extracted content.
        max_file_mb: The largest upload accepted, in megabytes. Reading stops just
            past it, so a larger file is refused without being held in memory.
        min_page_text_chars: The threshold below which a PDF page counts as having no text.
    """
    app = FastAPI(title="Knowledge ingestion API", docs_url="/docs", redoc_url=None)

    @app.middleware("http")
    async def bind_request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = _request_id_of(request)
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
        response.headers[REQUEST_ID_HEADER] = request_id
        log.info(
            "api_request_handled",
            request_id=request_id,
            method=request.method,
            route=request.url.path,
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        return response

    @app.exception_handler(ProjectError)
    async def project_error(request: Request, error: ProjectError) -> JSONResponse:
        log.warning("api_request_failed", request_id=request.state.request_id, code=error.code)
        return _problem(problem_from_error(error, request_id=request.state.request_id))

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
        problems = [
            {"field": ".".join(str(part) for part in item["loc"]), "problem": str(item["msg"])}
            for item in error.errors()
        ]
        return await project_error(request, RequestInvalidError(problems))

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception) -> JSONResponse:
        log.error(
            "api_request_failed",
            request_id=request.state.request_id,
            code="UNEXPECTED_ERROR",
            exc_info=error,
        )
        return _problem(problem_for_unexpected_error(request_id=request.state.request_id))

    @app.get("/health")
    def health() -> dict[str, str]:
        """Return `ok` while the API process is up."""
        return {"status": "ok"}

    @app.post("/knowledge-items", status_code=ACCEPTED)
    def submit(
        response: Response,
        file: Annotated[UploadFile, File(description="A DOC, DOCX or PDF file.")],
        node_id: Annotated[str, Form(description="Id of the owning Node, as in the registry.")],
        confidentiality: Annotated[ConfidentialityLevel, Form()] = ConfidentialityLevel.INTERNAL,
        usage_scope: Annotated[str | None, Form()] = None,
        document_type: Annotated[str | None, Form()] = None,
        domain: Annotated[str | None, Form()] = None,
        subdomain: Annotated[str | None, Form()] = None,
        project: Annotated[str | None, Form()] = None,
        author: Annotated[str | None, Form()] = None,
        source_reliability: Annotated[str | None, Form()] = None,
        tags: Annotated[list[str] | None, Form()] = None,
        related_issue_ids: Annotated[list[str] | None, Form()] = None,
        related_executor_ids: Annotated[list[str] | None, Form()] = None,
        related_rfp_ids: Annotated[list[str] | None, Form()] = None,
    ) -> dict[str, Any]:
        """Register a file for a Node and queue its ingestion. Returns 202 with its ingestion."""
        if not file.filename:
            raise RequestInvalidError([{"field": "file", "problem": "The file has no name."}])
        # One byte past the limit is enough for the use case to refuse the file.
        content = file.file.read(max_file_mb * BYTES_PER_MB + 1)
        receipt = submit_handler.submit(
            SubmitKnowledgeItem(
                owner_node_id=NodeIdentifier(node_id),
                source_file_name=file.filename,
                content=content,
                scope=KnowledgeScope(confidentiality=confidentiality, usage_scope=usage_scope),
                metadata=MetadataRecord(
                    domain=domain,
                    subdomain=subdomain,
                    project=project,
                    author=author,
                    document_type=document_type,
                    related_issue_ids=tuple(related_issue_ids or ()),
                    related_executor_ids=tuple(related_executor_ids or ()),
                    related_rfp_ids=tuple(related_rfp_ids or ()),
                    tags=tuple(tags or ()),
                    source_reliability=source_reliability,
                ),
                request_id=_request_id(),
            )
        )
        response.headers["Location"] = f"/knowledge-ingestions/{receipt.ingestion_id}"
        return receipt_body(receipt)

    @app.get("/knowledge-ingestions/{ingestion_id}")
    def status(ingestion_id: str) -> dict[str, Any]:
        """Return the status of an ingestion."""
        return ingestion_body(queries.get_ingestion(ingestion_id))

    @app.get("/knowledge-items/{item_id}/versions/{version_tag}/content")
    def show_content(
        item_id: str,
        version_tag: str,
        limit: Annotated[int | None, Query(ge=1, description="Blocks to return.")] = None,
    ) -> dict[str, Any]:
        """Return the blocks extracted from a version, in reading order."""
        found_tag, extracted = queries.get_content(item_id, VersionTag(version_tag))
        return content_body(
            item_id, found_tag, extracted, min_page_text_chars=min_page_text_chars, limit=limit
        )

    @app.post("/knowledge-items/{item_id}/versions/{version_tag}/ingestions", status_code=ACCEPTED)
    def reingest(item_id: str, version_tag: str, response: Response) -> dict[str, Any]:
        """Queue a version for ingestion again. Returns 202 with the new ingestion."""
        receipt = reingest_handler.reingest(
            ReingestKnowledgeItem(
                item_id=item_id, version_tag=VersionTag(version_tag), request_id=_request_id()
            )
        )
        response.headers["Location"] = f"/knowledge-ingestions/{receipt.ingestion_id}"
        return receipt_body(receipt)

    return app


def run_api(settings: Settings) -> None:
    """Serve the API on `API_HOST`:`API_PORT` until stopped."""
    configure_logging(settings)
    knowledge = build_knowledge(settings)
    app = create_app(
        submit_handler=knowledge.submit_handler,
        reingest_handler=knowledge.reingest_handler,
        queries=knowledge.queries,
        max_file_mb=settings.max_file_mb,
        min_page_text_chars=settings.min_page_text_chars,
    )
    log.info("api_started", host=settings.api_host, port=settings.api_port)
    try:
        # Uvicorn's own logs are off; the middleware writes one JSON line per request.
        uvicorn.run(
            app, host=settings.api_host, port=settings.api_port, access_log=False, log_config=None
        )
    finally:
        knowledge.close()
        log.info("api_stopped")


def _request_id_of(request: Request) -> str:
    sent = request.headers.get(REQUEST_ID_HEADER, "")
    return sent if _REQUEST_ID.fullmatch(sent) else uuid.uuid4().hex[:8]


def _problem(body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(body, status_code=body["status"], media_type=PROBLEM_MEDIA_TYPE)


def _request_id() -> str | None:
    bound: str | None = structlog.contextvars.get_contextvars().get("request_id")
    return bound
