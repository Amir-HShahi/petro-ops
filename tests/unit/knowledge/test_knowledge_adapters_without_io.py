from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from offline_rag.knowledge.application.errors import OwnerNodeNotFoundError
from offline_rag.knowledge.domain.errors import (
    InvalidKnowledgeVersionHistoryError,
    UnsupportedDocumentFormatError,
)
from offline_rag.knowledge.infrastructure.errors import KnowledgeStorageError
from offline_rag.knowledge.infrastructure.in_process_event_publisher import (
    InProcessEventPublisher,
)
from offline_rag.knowledge.infrastructure.system_clock import SystemClock
from offline_rag.knowledge.infrastructure.uuid_id_generator import UuidIdGenerator
from offline_rag.knowledge.interface.problem_details import (
    problem_for_unexpected_error,
    problem_from_error,
)
from offline_rag.shared_kernel.domain_event import DomainEvent
from offline_rag.shared_kernel.errors import ProjectError
from offline_rag.shared_kernel.node_identifier import NodeIdentifier

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)


class FirstEvent(DomainEvent):
    pass


class SecondEvent(DomainEvent):
    pass


def test_system_clock_returns_current_utc_time_when_asked():
    now = SystemClock().now()

    assert now.tzinfo is UTC
    assert abs(datetime.now(UTC) - now) < timedelta(seconds=5)


def test_id_generator_returns_new_uuid_when_asked_twice():
    generator = UuidIdGenerator()

    first, second = generator.new_id(), generator.new_id()

    assert first != second
    assert UUID(first).version == 4


def test_publisher_calls_only_matching_subscribers_in_order_when_events_are_published():
    publisher = InProcessEventPublisher()
    received: list[tuple[str, DomainEvent]] = []
    publisher.subscribe(FirstEvent, lambda event: received.append(("first", event)))
    publisher.subscribe(DomainEvent, lambda event: received.append(("any", event)))
    first, second = FirstEvent(occurred_at=NOW), SecondEvent(occurred_at=NOW)

    publisher.publish([first, second])

    assert received == [("first", first), ("any", first), ("any", second)]


@pytest.mark.parametrize(
    ("error", "status", "title"),
    [
        (UnsupportedDocumentFormatError("photo.png"), 422, "Request breaks a rule"),
        (OwnerNodeNotFoundError(NodeIdentifier("unknown_node")), 404, "Not found"),
        (KnowledgeStorageError(operation="add"), 503, "Service unavailable"),
        (InvalidKnowledgeVersionHistoryError("ki-1", "no versions."), 500, "Unexpected error"),
    ],
)
def test_problem_details_follow_the_error_contract_when_error_is_known(
    error: ProjectError, status: int, title: str
):
    problem = problem_from_error(error, request_id="3f9c1e2a")

    assert problem == {
        "type": error.code,
        "title": title,
        "status": status,
        "detail": error.message,
        "request_id": "3f9c1e2a",
        "details": dict(error.details),
    }


def test_problem_details_hide_the_cause_when_error_is_unexpected():
    problem = problem_for_unexpected_error(request_id="3f9c1e2a")

    assert problem["type"] == "UNEXPECTED_ERROR"
    assert problem["status"] == 500
    assert problem["request_id"] == "3f9c1e2a"
    assert problem["details"] == {}
