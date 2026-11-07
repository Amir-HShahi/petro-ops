"""Queue counts of the ingestion workers, read from RabbitMQ's management HTTP API (ADR 0008)."""

import base64
import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from offline_rag.knowledge.application.ports import IngestionQueueDepth
from offline_rag.knowledge.infrastructure.errors import QueueMonitorUnavailableError
from offline_rag.knowledge.infrastructure.rabbitmq_topology import (
    DEAD_LETTER_QUEUE,
    QUEUE_BY_LANE,
    RETRY_QUEUE,
)

INGESTION_QUEUES = (*QUEUE_BY_LANE.values(), RETRY_QUEUE, DEAD_LETTER_QUEUE)
# The page polls about once a second, so a slow broker must not pile up requests.
_REQUEST_TIMEOUT_S = 2


class RabbitMqManagementQueueMonitor:
    """Reads every ingestion queue of one virtual host with a single request."""

    def __init__(self, management_url: str, *, virtual_host: str) -> None:
        """Create the monitor.

        Args:
            management_url: The management API with its user and password, such as
                `http://user:secret@127.0.0.1:15672`. Settings allow loopback hosts only.
            virtual_host: The virtual host the queues live in, such as `/`.
        """
        parts = urlsplit(management_url)
        host = parts.hostname or ""
        netloc = f"[{host}]" if ":" in host else host
        if parts.port is not None:
            netloc += f":{parts.port}"
        self._queues_url = (
            f"{parts.scheme}://{netloc}{parts.path.rstrip('/')}/api/queues/"
            f"{quote(virtual_host, safe='')}?columns=name,messages_ready,"
            "messages_unacknowledged,consumers"
        )
        credentials = f"{unquote(parts.username or '')}:{unquote(parts.password or '')}"
        self._authorization = "Basic " + base64.b64encode(credentials.encode()).decode("ascii")

    def get_queue_depths(self) -> list[IngestionQueueDepth]:
        """Return the depth of every ingestion queue; one not declared yet counts as empty.

        The management plugin samples its counts, every 5 s by default, so they
        can trail the real queue by that much.

        Raises:
            QueueMonitorUnavailableError: The API cannot be reached, refuses the
                credentials or answers in an unknown shape.
        """
        request = urllib.request.Request(
            self._queues_url, headers={"Authorization": self._authorization}
        )
        try:
            with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_S) as response:
                listed: list[dict[str, Any]] = json.loads(response.read())
            by_name = {queue["name"]: queue for queue in listed}
            return [_depth(name, by_name.get(name, {})) for name in INGESTION_QUEUES]
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise QueueMonitorUnavailableError from error


def _depth(name: str, queue: dict[str, Any]) -> IngestionQueueDepth:
    # A queue that has never held a message may come back without the counts.
    return IngestionQueueDepth(
        queue=name,
        messages_ready=int(queue.get("messages_ready", 0)),
        messages_unacked=int(queue.get("messages_unacknowledged", 0)),
        consumers=int(queue.get("consumers", 0)),
    )
