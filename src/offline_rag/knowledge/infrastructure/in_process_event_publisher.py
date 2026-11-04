"""Domain events delivered in the same process, right after an aggregate is saved.

This is the default of AOQ 3 in `docs/application-services.md`. An event is lost
if the process stops between the save and the publish.
"""

from collections.abc import Callable, Sequence

import structlog

from offline_rag.shared_kernel.domain_event import DomainEvent

log = structlog.get_logger()

EventSubscriber = Callable[[DomainEvent], None]


class InProcessEventPublisher:
    """Calls each subscriber of an event's type, in the order they subscribed."""

    def __init__(self) -> None:
        """Start with no subscribers."""
        self._subscribers: list[tuple[type[DomainEvent], EventSubscriber]] = []

    def subscribe(self, event_type: type[DomainEvent], subscriber: EventSubscriber) -> None:
        """Call `subscriber` for every published event of `event_type` or a subclass."""
        self._subscribers.append((event_type, subscriber))

    def publish(self, events: Sequence[DomainEvent]) -> None:
        """Hand each event to its subscribers, in order."""
        for event in events:
            log.debug("domain_event_published", event_type=type(event).__name__)
            for event_type, subscriber in self._subscribers:
                if isinstance(event, event_type):
                    subscriber(event)
