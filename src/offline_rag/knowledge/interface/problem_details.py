"""Errors turned into the RFC 9457 Problem Details format of `docs/errors.md`."""

from typing import Any

from offline_rag.shared_kernel.errors import (
    DomainError,
    InfrastructureError,
    NotFoundError,
    ProjectError,
)

UNEXPECTED_CODE = "UNEXPECTED_ERROR"
_UNEXPECTED_STATUS = 500

# Domain errors may also be 400 or 409; 422 fits "the request broke a rule" best
# until a code needs one of the others.
_STATUS_BY_CATEGORY: dict[type[ProjectError], int] = {
    DomainError: 422,
    NotFoundError: 404,
    InfrastructureError: 503,
}

_TITLE_BY_STATUS = {
    404: "Not found",
    422: "Request breaks a rule",
    500: "Unexpected error",
    503: "Service unavailable",
}


def problem_from_error(error: ProjectError, *, request_id: str) -> dict[str, Any]:
    """Return the Problem Details body for a project error."""
    status = _STATUS_BY_CATEGORY.get(error.category, _UNEXPECTED_STATUS)
    return {
        "type": error.code,
        "title": _TITLE_BY_STATUS[status],
        "status": status,
        "detail": error.message,
        "request_id": request_id,
        "details": dict(error.details),
    }


def problem_for_unexpected_error(*, request_id: str) -> dict[str, Any]:
    """Return the Problem Details body for an error that is not a project error.

    Nothing about the error itself is included; it goes to the logs instead.
    """
    return {
        "type": UNEXPECTED_CODE,
        "title": _TITLE_BY_STATUS[_UNEXPECTED_STATUS],
        "status": _UNEXPECTED_STATUS,
        "detail": "Something went wrong inside the core. Report it with the request id.",
        "request_id": request_id,
        "details": {},
    }
