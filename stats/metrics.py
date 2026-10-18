import logging

from prometheus_client.core import GaugeMetricFamily

from stats.queries import queue_size

logger = logging.getLogger(__name__)


class DatabaseCollector:
    def collect(self):
        try:
            size = queue_size()
        except Exception:
            logger.exception("Could not read the queue size for the metrics endpoint")
            return
        yield GaugeMetricFamily(
            "ticketing_queue_size",
            "Tickets without an assignee that are not resolved or closed.",
            value=size,
        )
